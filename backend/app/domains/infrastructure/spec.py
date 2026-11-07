"""Catalog of the software-infrastructure domain."""

from ..spec import DomainSpec, EntityType, EventType, FieldSpec, InterventionType, MetricDef, RelationshipType

CAPACITY = FieldSpec("capacity", "Capacity", unit="requests/s", min=0,
                     help="Most load the component handles without slowing down.")
LOAD = FieldSpec("current_load", "Current load", unit="requests/s", min=0,
                 help="Normal traffic. A traffic spike multiplies it.")
RECOVERY = FieldSpec("recovery_time", "Recovery time", unit="time units", min=0,
                     help="How long a failure lasts when the event has no duration.")
OVERLOAD = FieldSpec("overload_failure_ratio", "Fails above", unit="x capacity", default=1.5, min=1,
                     help="Load above capacity x this value makes the component fail, not just slow down.")

LATENCY = FieldSpec("latency", "Latency", unit="ms", min=0,
                    help="Time this component adds to a request when healthy. Optional: "
                         "set it to get end-to-end latency metrics.")
COST_RATE = FieldSpec("cost_per_time", "Running cost", unit="per time unit", min=0,
                      help="Optional. Used for the running-cost and total-cost metrics.")
LOAD_SHARE = FieldSpec("load_share", "Load share", unit="x extra load", min=0,
                       help="Optional. Share of the caller's extra load (above normal) passed on to "
                            "this dependency. Leave empty to keep spikes local.")


def _entity(type_: str, label: str, short: str, color: str, capacity: float | None, load: float | None,
            recovery: float | None = None, description: str = "", latency: float | None = None) -> EntityType:
    fields = []
    if capacity is not None:
        fields += [FieldSpec(**{**CAPACITY.__dict__, "default": capacity}),
                   FieldSpec(**{**LOAD.__dict__, "default": load})]
    fields.append(FieldSpec(**{**RECOVERY.__dict__, "default": recovery}))
    fields.append(OVERLOAD)
    fields.append(FieldSpec(**{**LATENCY.__dict__, "default": latency}))
    fields.append(COST_RATE)
    return EntityType(type_, label, short, color, tuple(fields), description)


INFRASTRUCTURE_SPEC = DomainSpec(
    name="software_infrastructure",
    label="Software infrastructure",
    description="Services, databases, caches and queues that depend on each other. "
                "Explore failures, traffic changes and architecture decisions.",
    time_unit="time units",
    entity_types=(
        _entity("gateway", "API Gateway", "GW", "#E9B85A", 1000, 600, description="Entry point for requests.", latency=5),
        _entity("service", "Service", "SV", "#8FB8E0", 800, 400, latency=20),
        _entity("database", "Database", "DB", "#CFA6E6", 1000, 600, 10, latency=15),
        _entity("cache", "Cache", "CA", "#F59A3E", 5000, 1000, latency=2),
        _entity("queue", "Queue", "QU", "#EBD48F", 2000, 500, latency=5),
        _entity("external", "External API", "EX", "#C9AE85", None, None, latency=80),
    ),
    relationship_types=(
        RelationshipType("requires", "Requires", "The source fails or degrades with the target.", "solid",
                         (LOAD_SHARE,)),
        RelationshipType("optional", "Optional", "Losing the target only degrades the source.", "dashed",
                         (LOAD_SHARE,)),
        RelationshipType("fallback", "Fallback", "Stands in for the target, but only in degraded mode.", "dotted",
                         (LOAD_SHARE,)),
    ),
    event_types=(
        EventType("component_failure", "Failure", "The component stops working."),
        EventType("component_recovery", "Recovery", "Clears a failure.", uses_duration=False),
        EventType("traffic_spike", "Traffic spike", "Multiplies the component's load.",
                  severity_label="Load multiplier"),
        EventType("latency_increase", "Latency increase", "The component slows down (degraded)."),
    ),
    intervention_types=(
        InterventionType("add_component", "Add component"),
        InterventionType("remove_component", "Remove component"),
        InterventionType("add_dependency", "Add dependency"),
        InterventionType("remove_dependency", "Remove dependency"),
        InterventionType("set_attribute", "Change a component attribute"),
        InterventionType("set_dependency_attribute", "Change a dependency attribute"),
        InterventionType("set_parameter", "Change a system parameter"),
    ),
    metrics=(
        MetricDef("availability", "Availability", "higher", format="percent",
                  description="Share of time the entry points were not failed."),
        MetricDef("downtime", "Downtime", "lower", "time units", "duration",
                  "Time any entry point was failed."),
        MetricDef("degraded_time", "Degraded time", "lower", "time units", "duration",
                  "Time the worst entry point was degraded."),
        MetricDef("affected_components", "Affected components", "lower", format="count",
                  description="Components that left healthy at any point."),
        MetricDef("recovery_time", "Recovery time", "lower", "time units", "duration",
                  "From the first problem until everything is healthy again."),
        MetricDef("cost", "Intervention cost", "lower", format="money",
                  description="Sum of the costs of the scenario's interventions."),
        MetricDef("mean_latency", "Mean latency", "lower", "ms",
                  description="Time-weighted end-to-end latency at the entry points while serving "
                              "(needs component latencies)."),
        MetricDef("peak_latency", "Peak latency", "lower", "ms",
                  description="Highest end-to-end latency at the entry points while serving."),
        MetricDef("sla_breach_time", "SLA breach time", "lower", "time units", "duration",
                  "Time latency was above the latency SLA or the service was down (needs a latency SLA)."),
        MetricDef("peak_utilisation", "Peak utilisation", "lower", format="percent",
                  description="Highest load / capacity reached by any component."),
        MetricDef("running_cost", "Running cost", "lower", format="money",
                  description="Sum of component running costs over the simulated window."),
        MetricDef("total_cost", "Total cost", "lower", format="money",
                  description="Intervention cost plus running cost."),
    ),
    risk_metric="downtime",
    open_entity_types=True,  # older systems may use custom component types
    features=("entry_points", "groups", "propagation_delay", "presets"),
    default_objectives=(("downtime", 3.0), ("degraded_time", 1.0), ("cost", 1.0),
                        ("mean_latency", 1.0), ("running_cost", 1.0)),
    assumptions=(
        "Rule-based model: a component is healthy, degraded or failed; no gradual slow-down yet.",
        "A failure lasts for the event's duration, or the component's recovery time.",
        "Traffic spikes only affect the component they target, unless a dependency has a load share: "
        "then that share of the caller's extra load is passed on (instantly; failed callers still forward it).",
        "Availability is measured at entry points (all components if none is marked).",
        "Latency is a sum along the call path: a component's own latency (x the degraded factor while "
        "degraded) plus the fastest healthy member of each dependency group. Calls are sequential; "
        "queueing delay is not modelled.",
        "Costs are the numbers you enter; they are not real prices.",
    ),
    parameters=(
        FieldSpec("latency_sla", "Latency SLA", unit="ms", min=0,
                  help="Optional target for end-to-end latency. Enables the SLA breach metric."),
        FieldSpec("degraded_latency_factor", "Degraded slowdown", unit="x", default=3, min=1,
                  help="How much slower a degraded component is."),
    ),
)
