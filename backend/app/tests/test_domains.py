"""Hospital patient flow and cold-chain logistics on the shared kernel (Phases 5-6).

Cold-chain cases are exact (demand is set to 0 where it would add noise).
Hospital cases check invariants and large, unambiguous effects, because
arrivals and treatment times are random.
"""

import pytest

from app.domains.coldchain.model import poisson
from app.domains.registry import get_domain
from app.models import Component, Dependency, Event, Status, System
from app.simulation.branching import Intervention, Scenario, run_scenario
from app.simulation.engine import explain
from app.simulation.montecarlo import run_monte_carlo

import random


def run(system, *events, until, interventions=(), seed=42):
    return run_scenario(system, Scenario("x", "x", events=list(events), interventions=list(interventions),
                                         seed=seed), until)


# ==== hospital ====================================================================
def hospital(ward_beds=20, ed_max_wait=None, rate=6.0) -> System:
    s = System("h", "Hospital", domain="hospital")
    s.add_component(Component("arr", "Arrivals", "arrivals", attributes={"rate": rate}))
    ed = {"capacity": 8, "service_time": 1.0, "hold_bed_while_waiting": True}
    if ed_max_wait:
        ed["max_wait"] = ed_max_wait
    s.add_component(Component("ed", "ED", "emergency", attributes=ed))
    s.add_component(Component("ward", "Ward", "ward", attributes={
        "capacity": ward_beds, "service_time": 12.0, "hold_bed_while_waiting": True}))
    s.add_dependency(Dependency("arr->ed", "arr", "ed", dependency_type="routes_to"))
    s.add_dependency(Dependency("ed->ward", "ed", "ward", dependency_type="routes_to",
                                attributes={"probability": 0.5}))
    return s


def test_hospital_runs_and_reports_every_metric_in_its_catalog():
    r = run(hospital(), until=48)
    keys = {m.key for m in get_domain("hospital").spec.metrics}
    assert keys == set(r.metrics) and r.domain == "hospital"
    assert r.metrics.patients_arrived > 200  # ~6/h for 48 h
    assert set(r.series) == {"queue", "in_use"} and len(r.series["queue"]["ed"]) == 121


def test_every_patient_is_accounted_for():
    r = run(hospital(ed_max_wait=2), until=48)
    model = r.state
    in_system = sum(1 for p in model.patients if not p.done)
    m = r.metrics
    assert m.patients_treated + m.left_without_treatment + in_system == m.patients_arrived


def test_same_seed_same_future_and_common_random_numbers_across_branches():
    a, b = run(hospital(), until=48), run(hospital(), until=48)
    assert a.metrics == b.metrics and [e.message for e in a.log] == [e.message for e in b.log]
    assert run(hospital(), until=48, seed=7).metrics != a.metrics
    # A decision that does not touch arrivals leaves the same patients arriving.
    more_beds = run(hospital(), until=48, interventions=[
        Intervention("b", "set_attribute", {"component_id": "ward", "key": "capacity", "value": 60})])
    assert more_beds.metrics.patients_arrived == a.metrics.patients_arrived


def test_a_full_ward_makes_patients_board_in_the_emergency_department():
    tight, roomy = run(hospital(ward_beds=6), until=72), run(hospital(ward_beds=80), until=72)
    assert tight.metrics.boarding_time > 50 and roomy.metrics.boarding_time == 0
    assert tight.metrics.mean_wait > roomy.metrics.mean_wait
    # The ED's crowding is blamed on the crowded ward it is boarding patients for.
    ed_bad = next(e for e in tight.log if e.component_id == "ed" and e.new_status == Status.DEGRADED
                  and e.cause_id is not None)
    assert tight.log[ed_bad.cause_id].component_id == "ward"


def test_patients_leave_after_max_wait_when_a_unit_is_closed():
    r = run(hospital(ed_max_wait=1.5), Event("close", "unit_closure", "ed", 0, 100), until=24)
    m = r.metrics
    assert m.patients_treated == 0 and m.mean_length_of_stay is None
    # Everyone who arrived more than 1.5 h before the end has given up.
    late = sum(1 for p in r.state.patients if p.arrived > 24 - 1.5)
    assert m.left_without_treatment == m.patients_arrived - late
    failed = next(e for e in r.log if e.component_id == "ed" and e.new_status == Status.FAILED)
    assert explain(r.log, failed.id)[0].message == "unit closure begins"


def test_surge_and_staff_shortage():
    base = run(hospital(), until=48)
    surge = run(hospital(), Event("s", "arrival_surge", "arr", 0, 48, severity=2), until=48)
    assert surge.metrics.patients_arrived > 1.6 * base.metrics.patients_arrived
    assert surge.timelines["arr"][0] == (0, Status.DEGRADED)  # replaces the starting status at t=0
    short = run(hospital(), Event("sh", "staff_shortage", "ed", 0, 48, severity=4), until=48)
    assert short.metrics.mean_wait > base.metrics.mean_wait
    slow = run(hospital(), Event("sl", "service_slowdown", "ed", 0, 48, severity=3), until=48)
    assert slow.metrics.mean_wait > base.metrics.mean_wait


def test_routing_shares_send_about_the_right_number_of_patients():
    r = run(hospital(ward_beds=500), until=200)
    model = r.state
    ward_admissions = model.units["ward"].busy_area  # patient-hours on the ward
    ed_admissions = len(model.patients)
    # 50% go to the ward for 12 h on average: about 0.5 x arrivals x 12 patient-hours.
    expected = 0.5 * ed_admissions * 12
    assert 0.75 * expected < ward_admissions < 1.15 * expected


def test_hospital_validation():
    domain = get_domain("hospital")
    s = hospital()
    s.dependencies[1].attributes["probability"] = 1.5
    assert any("between 0 and 1" in p for p in domain.errors(s))
    s = hospital()
    s.add_dependency(Dependency("ed->ward2", "ed", "ward", dependency_type="routes_to",
                                attributes={"probability": 0.7}))
    assert any("at most 100%" in p for p in domain.errors(s))
    s = hospital()
    s.add_component(Component("db", "db", "database"))
    assert any("not used in Hospital operations" in p for p in domain.errors(s))
    s = System("h", "h", domain="hospital")
    s.add_component(Component("ed", "ED", "emergency"))
    assert any("Patient arrivals" in p for p in domain.errors(s))
    with pytest.raises(ValueError, match="limit"):
        run(hospital(rate=5000), until=100)


def test_hospital_monte_carlo_uses_mean_wait_as_risk():
    mc = run_monte_carlo(hospital(ward_beds=8), Scenario("x", "x", seed=1), until=24, runs=10)
    assert mc.aggregates is None and mc.risk_metric == "mean_wait"
    assert mc.metric_stats["mean_wait"].mean > 0 and len(mc.risk_values()) == 10


# ==== cold chain ==================================================================
def chain(store_inventory=40, demand=0.0, dc_backup=0.0, tolerance=2.0) -> System:
    """supplier -> warehouse -> dc -> store, plus a slower direct warehouse -> store route."""
    s = System("c", "Cold chain", domain="cold_chain", parameters={"max_excursion_hours": tolerance, "unit_value": 10})
    s.add_component(Component("sup", "Supplier", "supplier", attributes={"lead_time": 10}))
    s.add_component(Component("wh", "Warehouse", "warehouse", attributes={"inventory": 1000, "holding_cost": 0}))
    s.add_component(Component("dc", "DC", "distribution", attributes={
        "inventory": 100, "holding_cost": 0.01, "backup_power_hours": dc_backup}))
    s.add_component(Component("st", "Store", "store", attributes={
        "inventory": store_inventory, "reorder_point": 50, "order_quantity": 60, "demand_rate": demand,
        "holding_cost": 0}))
    s.add_dependency(Dependency("sup-wh", "sup", "wh", dependency_type="ships_to", attributes={"travel_time": 5}))
    s.add_dependency(Dependency("wh-dc", "wh", "dc", dependency_type="ships_to", attributes={"travel_time": 4}))
    s.add_dependency(Dependency("dc-st", "dc", "st", dependency_type="ships_to",
                                attributes={"travel_time": 3, "cost_per_unit": 0.5}))
    s.add_dependency(Dependency("wh-st", "wh", "st", dependency_type="ships_to",
                                attributes={"travel_time": 8, "cost_per_unit": 1.0}))
    return s


def test_order_takes_the_fastest_route_and_costs_are_exact():
    r = run(chain(), until=24)
    m, model = r.metrics, r.state
    # Store starts at 40 <= reorder point 50, orders 60 from the DC (3 h, the fastest source).
    assert (m.on_time_rate, m.mean_delivery_time, m.reroutes) == (1.0, 3, 0)
    assert m.transport_cost == 60 * 0.5
    assert model.sites["st"].on_hand == 100 and model.sites["dc"].on_hand == 40
    # Holding cost: DC holds 100 units for 0 h (shipped at t=0), then 40 units for 24 h at 0.01.
    assert m.holding_cost == pytest.approx(40 * 24 * 0.01)
    assert m.fill_rate == 1.0 and m.total_cost == pytest.approx(30 + 9.6)


def test_a_closed_route_reroutes_the_order_and_it_arrives_late():
    r = run(chain(), Event("close", "route_closure", "dc-st", 0, 24), until=24)
    m = r.metrics
    assert (m.mean_delivery_time, m.reroutes, m.on_time_rate) == (8, 1, 0.0)
    order = next(e for e in r.log if "via wh -> st" in e.message)
    assert "8 h instead of 3 h" in order.message
    assert explain(r.log, order.id)[0].message == "route closure begins"
    assert r.timelines["dc-st"][0:2] == [(0, Status.HEALTHY), (0, Status.FAILED)] or \
        r.timelines["dc-st"][0] == (0, Status.FAILED)


def test_no_open_route_is_logged_and_nothing_arrives():
    r = run(chain(), Event("a", "route_closure", "dc-st", 0, 24), Event("b", "route_closure", "wh-st", 0, 24),
            until=24)
    assert r.metrics.mean_delivery_time is None
    assert any(e.message == "no open route can supply this site" for e in r.log)


def test_power_outage_beyond_backup_discards_stock_at_the_tolerance():
    r = run(chain(store_inventory=200), Event("po", "power_outage", "dc", 10, 5), until=24)
    m = r.metrics
    assert m.units_discarded == 100 and m.discard_cost == 1000
    assert m.exposed_unit_hours == pytest.approx(200, abs=0.01)  # 100 units x 2 h
    discard = next(e for e in r.log if "discarded" in e.message)
    assert discard.time == pytest.approx(12, abs=1e-3)
    assert explain(r.log, discard.id)[0].message == "power outage begins"
    assert r.timelines["dc"][1] == (10, Status.DEGRADED)


def test_backup_power_longer_than_the_outage_prevents_any_exposure():
    r = run(chain(store_inventory=200, dc_backup=6), Event("po", "power_outage", "dc", 10, 5), until=24)
    assert (r.metrics.units_discarded, r.metrics.exposed_unit_hours) == (0, 0)


def test_refrigeration_failure_exposes_shipments_on_the_route():
    # The 60-unit shipment travels dc -> st from t=0 to t=3; the failure overlaps it for 2 h.
    r = run(chain(tolerance=1), Event("rf", "reefer_failure", "dc-st", 1, 3), until=24)
    assert r.metrics.exposed_unit_hours == pytest.approx(120)
    assert r.metrics.units_discarded == 60
    ok = run(chain(tolerance=3), Event("rf", "reefer_failure", "dc-st", 1, 3), until=24)
    assert ok.metrics.units_discarded == 0


def test_unrefrigerated_routes_count_the_whole_trip():
    s = chain(tolerance=5)
    s.dependencies[2].attributes["refrigerated"] = False
    r = run(s, until=24)
    assert r.metrics.exposed_unit_hours == 60 * 3 and r.metrics.units_discarded == 0


def test_supplier_delay_makes_replenishment_late():
    s = chain()
    s.components["wh"].attributes.update({"inventory": 0, "reorder_point": 10, "order_quantity": 100})
    s.components["dc"].attributes["inventory"] = 0
    r = run(s, Event("d", "supplier_delay", "sup", 0, 24, severity=2), until=48)
    late = [e for e in r.log if "instead of" in e.message]
    assert late and explain(r.log, late[0].id)[0].message == "supplier delay begins"


def test_demand_lost_sales_and_stockouts():
    s = chain(store_inventory=0, demand=5)
    s.dependencies = []  # nothing can be delivered
    r = run(s, until=48)
    m = r.metrics
    assert m.fill_rate == 0 and m.lost_sales > 150 and m.stockout_time == 48
    assert r.timelines["st"][0] == (0, Status.FAILED)


def test_every_branch_sees_the_same_customers():
    a = run(chain(demand=4), until=72)
    b = run(chain(demand=4), until=72, interventions=[
        Intervention("rp", "set_attribute", {"component_id": "st", "key": "reorder_point", "value": 150})])
    assert a.state.totals["demand"] == b.state.totals["demand"]


def test_poisson_sampler_has_the_right_mean():
    rng = random.Random(1)
    for lam in (0.5, 4, 50):
        mean = sum(poisson(rng, lam) for _ in range(4000)) / 4000
        assert mean == pytest.approx(lam, rel=0.06)
    assert poisson(rng, 0) == 0


def test_cold_chain_validation():
    domain = get_domain("cold_chain")
    s = chain()
    s.dependencies[0].attributes["travel_time"] = 0
    assert any("travel time" in p for p in domain.errors(s))
    s = chain()
    s.add_dependency(Dependency("wh-sup", "wh", "sup", dependency_type="ships_to"))
    assert any("suppliers cannot receive" in p for p in domain.errors(s))
    s = chain()
    s.dependencies.append(Dependency("x", "st", "dc", dependency_type="routes_to"))
    assert any("not used in Cold-chain" in p for p in domain.errors(s))


def test_relationship_events_are_rejected_by_other_domains():
    with pytest.raises(ValueError, match="not used in Hospital"):
        run(hospital(), Event("rf", "reefer_failure", "arr->ed", 1, 2), until=10)


def test_hospital_queue_matches_queueing_theory():
    """M/M/1 check: one bed, Poisson arrivals (0.5/h), exponential treatment (mean 1 h).

    Queueing theory says the average wait in the queue is rho / (mu - lambda) = 0.5 / 0.5 = 1 hour
    and the bed is busy rho = 50% of the time. Over ~10,000 patients the simulation should agree
    within a few percent (it starts empty, which slightly lowers the average).
    """
    s = System("mm1", "M/M/1", domain="hospital")
    s.add_component(Component("arr", "Arrivals", "arrivals", attributes={"rate": 0.5}))
    s.add_component(Component("bed", "Bed", "ward", attributes={"capacity": 1, "service_time": 1.0}))
    s.add_dependency(Dependency("arr->bed", "arr", "bed", dependency_type="routes_to"))
    waits, util = [], []
    for seed in (1, 2, 3):
        r = run(s, until=20_000, seed=seed)
        waits.append(r.metrics.mean_wait)
        util.append(r.metrics.bottleneck_utilisation)
    assert sum(waits) / 3 == pytest.approx(1.0, rel=0.08)
    assert sum(util) / 3 == pytest.approx(0.5, rel=0.03)
