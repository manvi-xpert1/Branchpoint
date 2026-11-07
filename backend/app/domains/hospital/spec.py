"""Catalog of the hospital operations and patient-flow domain.

An operational planning model: it is about queues, beds and staff, not
about patients' health. It makes no clinical claims.
"""

from ..spec import DomainSpec, EntityType, EventType, FieldSpec, InterventionType, MetricDef, RelationshipType

RATE = FieldSpec("rate", "Arrival rate", unit="patients/hour", min=0, default=6,
                 help="Average number of patients arriving per hour (random, Poisson).")
CAPACITY = FieldSpec("capacity", "Beds / staff", kind="integer", unit="patients at once", min=0,
                     help="How many patients the unit can treat at the same time.")
SERVICE = FieldSpec("service_time", "Mean time in unit", unit="hours", min=0,
                    help="Average time a patient spends being treated here (random, exponential).")
MAX_WAIT = FieldSpec("max_wait", "Leaves after waiting", unit="hours", min=0,
                     help="Optional. Patients still waiting for this unit after this long leave before "
                          "treatment. Only applies to patients not already holding a bed elsewhere.")
CROWDED = FieldSpec("crowding_queue", "Crowded at queue of", kind="integer", unit="patients", min=1,
                    help="Queue length at which the unit counts as crowded (degraded). Default: its capacity, at least 5.")
HOLD = FieldSpec("hold_bed_while_waiting", "Keeps bed while waiting to move", kind="boolean",
                 help="If on, a patient who is ready to move on but finds the next unit full stays in "
                      "this unit's bed (boarding) and blocks it.")
OCCUPIED = FieldSpec("occupied_at_start", "Occupied at start", kind="integer", unit="patients", min=0,
                     help="Patients already in the unit when the window starts (a hospital rarely starts "
                          "empty). They are not counted as arrivals or in the wait figures.")
COST = FieldSpec("cost_per_hour", "Cost per bed/staff hour", unit="per hour", min=0,
                 help="Optional. Used for the staffing-cost metric.")


def _unit(type_: str, label: str, short: str, color: str, capacity: int, service: float,
          hold: bool, description: str) -> EntityType:
    return EntityType(type_, label, short, color, (
        FieldSpec(**{**CAPACITY.__dict__, "default": capacity}),
        FieldSpec(**{**SERVICE.__dict__, "default": service}),
        MAX_WAIT, CROWDED, OCCUPIED,
        FieldSpec(**{**HOLD.__dict__, "default": hold}),
        COST,
    ), description)


HOSPITAL_SPEC = DomainSpec(
    name="hospital",
    label="Hospital operations",
    description="Patient flow through triage, emergency, diagnostics, wards and ICU. Explore surges, "
                "staff shortages and capacity decisions. An operational model, not clinical advice.",
    time_unit="hours",
    entity_types=(
        EntityType("arrivals", "Patient arrivals", "AR", "#E9B85A", (RATE,),
                   "Where patients come from. Connect it to the first unit(s) they visit."),
        _unit("triage", "Triage", "TR", "#8FB8E0", 2, 0.15, False, "First assessment."),
        _unit("emergency", "Emergency dept.", "ED", "#FF8FA3", 10, 3.0, True, "Emergency treatment bays."),
        _unit("diagnostics", "Diagnostics", "DX", "#CFA6E6", 3, 0.5, False, "Imaging and lab tests."),
        _unit("ward", "Ward", "WD", "#7CD1AB", 30, 48.0, True, "Inpatient beds."),
        _unit("icu", "ICU", "IC", "#F59A3E", 6, 72.0, True, "Intensive care beds."),
    ),
    relationship_types=(
        RelationshipType("routes_to", "Routes to",
                         "Share of patients who go from the source to the target next. Shares from one "
                         "unit add up to at most 1; the rest are discharged.", "solid",
                         (FieldSpec("probability", "Share of patients", kind="probability", default=1.0,
                                    min=0, max=1),)),
    ),
    event_types=(
        EventType("arrival_surge", "Arrival surge", "More patients arrive (target: an arrivals node).",
                  severity_label="Arrival multiplier"),
        EventType("staff_shortage", "Staff shortage", "Fewer beds/staff available in a unit.",
                  severity_label="Beds/staff unavailable"),
        EventType("unit_closure", "Unit closure", "The unit takes no new patients; patients queue."),
        EventType("service_slowdown", "Slowdown", "Treatment takes longer (e.g. IT outage, lab delays).",
                  severity_label="Time multiplier"),
    ),
    intervention_types=(
        InterventionType("set_attribute", "Change a unit setting", "e.g. add beds or staff"),
        InterventionType("set_dependency_attribute", "Change a routing share"),
        InterventionType("set_parameter", "Change a system parameter"),
        InterventionType("add_component", "Add a unit"),
        InterventionType("remove_component", "Remove a unit"),
        InterventionType("add_dependency", "Add a route"),
        InterventionType("remove_dependency", "Remove a route"),
    ),
    metrics=(
        MetricDef("mean_wait", "Mean wait", "lower", "hours", "duration",
                  "Average time a patient spent waiting in queues (patients still waiting count up to the end)."),
        MetricDef("p95_wait", "95th percentile wait", "lower", "hours", "duration",
                  "1 in 20 patients waited longer than this in total."),
        MetricDef("left_without_treatment", "Left before treatment", "lower", format="count",
                  description="Patients who gave up waiting (needs a 'leaves after waiting' setting)."),
        MetricDef("left_rate", "Left before treatment rate", "lower", format="percent",
                  description="Share of arriving patients who left before treatment."),
        MetricDef("patients_treated", "Patients discharged", "higher", format="count",
                  description="Patients who completed their path within the window."),
        MetricDef("mean_length_of_stay", "Mean length of stay", "lower", "hours", "duration",
                  "Arrival to discharge, for discharged patients."),
        MetricDef("boarding_time", "Boarding time", "lower", "hours", "duration",
                  "Total patient-hours spent holding a bed while waiting for the next unit."),
        MetricDef("peak_queue", "Peak queue", "lower", format="count",
                  description="Longest queue at any unit."),
        MetricDef("bottleneck_utilisation", "Bottleneck utilisation", "lower", format="percent",
                  description="Average share of beds/staff in use at the busiest unit."),
        MetricDef("crowded_time", "Crowded time", "lower", "hours", "duration",
                  "Time at least one unit was crowded or closed with patients waiting."),
        MetricDef("patients_arrived", "Patients arrived", "neutral", format="count"),
        MetricDef("staff_cost", "Staffing cost", "lower", format="money",
                  description="Beds/staff x cost per hour x hours (needs costs on units)."),
        MetricDef("cost", "Intervention cost", "lower", format="money"),
        MetricDef("total_cost", "Total cost", "lower", format="money",
                  description="Staffing cost plus intervention cost."),
    ),
    risk_metric="mean_wait",
    default_objectives=(("mean_wait", 3.0), ("left_without_treatment", 2.0), ("boarding_time", 1.0),
                        ("total_cost", 1.0)),
    assumptions=(
        "Operational planning model only. It does not model diagnoses, acuity, treatment quality or "
        "patient outcomes, and must not be used for clinical decisions.",
        "Arrivals are random (Poisson) at the given average rate; time in each unit is random "
        "(exponential) around its mean.",
        "Each patient's next step is drawn from the routing shares. Shares from a unit that add up to "
        "less than 1 mean the rest are discharged.",
        "Queues are first come, first served; there is no prioritisation by urgency.",
        "Patients already in a unit at the start ('occupied at start') have a fresh random remaining time "
        "there and then follow the normal routes; they are left out of arrival and wait figures.",
        "Each patient uses the same random numbers in every branch (common random numbers), so "
        "differences between futures come from the decisions.",
        "All numbers are illustrative inputs you provide, not real hospital data.",
    ),
    parameters=(),
    default_until=72.0,
    edge_meaning="The arrow shows where patients go next.",
)
