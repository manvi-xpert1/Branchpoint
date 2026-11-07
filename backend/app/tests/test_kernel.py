"""The shared kernel and the domain catalog (Phase 2)."""

import pytest

from app.domains.registry import all_domains, get_domain
from app.models import Component, Dependency, Event, System
from app.simulation.branching import Intervention, Scenario, run_scenario
from app.simulation.event_queue import START
from app.simulation.kernel import Kernel, SimulationError


# ---- kernel -----------------------------------------------------------------
def test_items_are_handled_in_time_order_and_the_clock_follows():
    k = Kernel(until=10)
    seen = []
    for t in (5, 1, 3):
        k.at(t, "tick", f"x{t}")
    k.run(lambda item: seen.append((k.now, item.component_id)))
    assert seen == [(1, "x1"), (3, "x3"), (5, "x5")]
    assert k.now == 10  # the clock ends at `until`


def test_items_after_the_end_time_are_not_handled():
    k = Kernel(until=4)
    k.at(2, "tick", "a")
    k.at(6, "tick", "b")
    seen = []
    k.run(lambda item: seen.append(item.component_id))
    assert seen == ["a"]


def test_handlers_can_schedule_follow_ups_relative_to_now():
    k = Kernel(until=10)
    k.at(1, "ping", "a")
    times = []

    def handle(item):
        times.append(k.now)
        if k.now < 4:
            k.after(1.5, "ping", "a")

    k.run(handle)
    assert times == [1, 2.5, 4]


def test_custom_priority_breaks_ties_at_the_same_time():
    k = Kernel(until=5)
    k.at(1, "late", "b", priority=9)
    k.at(1, "early", "a", priority=0)
    order = []
    k.run(lambda item: order.append(item.kind))
    assert order == ["early", "late"]


def test_log_entries_link_to_their_cause():
    k = Kernel(until=5)
    first = k.log_entry(kind="event", component_id="a", message="start")
    second = k.log_entry(kind="status_change", component_id="b", message="broke", cause_id=first.id)
    assert (second.cause_id, k.log[second.id]) == (first.id, second)


def test_step_guard_stops_endless_runs():
    k = Kernel(until=10, max_steps=5)
    k.at(0, "loop", "a")
    with pytest.raises(SimulationError):
        k.run(lambda item: k.after(0, "loop", "a"))


def test_named_streams_are_reproducible_and_independent():
    a, b = Kernel(until=1, seed=7), Kernel(until=1, seed=7)
    assert [a.stream("arrivals").random() for _ in range(3)] == [b.stream("arrivals").random() for _ in range(3)]
    # Using another stream does not shift the "arrivals" numbers (common random numbers).
    c = Kernel(until=1, seed=7)
    c.stream("demand").random()
    c_arrivals = [c.stream("arrivals").random() for _ in range(3)]
    d = Kernel(until=1, seed=7)
    assert c_arrivals == [d.stream("arrivals").random() for _ in range(3)]
    assert Kernel(until=1, seed=8).stream("arrivals").random() != Kernel(until=1, seed=7).stream("arrivals").random()


def test_event_sampling_ignores_the_order_events_are_listed_in():
    events = [Event(f"e{i}", "component_failure", "a", float(i), probability=0.5) for i in range(6)]
    first = Kernel(until=10, seed=3).sample_events(events)
    second = Kernel(until=10, seed=3).sample_events(list(reversed(events)))
    assert [e.id for e in first[0]] == [e.id for e in second[0]] and first[1] == second[1]


# ---- catalog ----------------------------------------------------------------
def test_infrastructure_catalog_describes_every_metric_a_run_reports():
    domain = get_domain("software_infrastructure")
    s = System("s", "s")
    s.add_component(Component("a", "a", "service", entry_point=True))
    result = run_scenario(s, Scenario("x", "x"), until=10)
    spec_keys = {m.key for m in domain.spec.metrics}
    assert spec_keys <= set(result.metrics)
    assert domain.spec.risk_metric in spec_keys
    assert all(m.better in ("lower", "higher", "neutral") for m in domain.spec.metrics)


def test_catalog_is_serialisable_and_lists_entity_fields():
    spec = get_domain("software_infrastructure").spec.to_dict()
    db = next(e for e in spec["entity_types"] if e["type"] == "database")
    assert {f["key"] for f in db["fields"]} >= {"capacity", "current_load", "recovery_time"}
    assert {d.name for d in all_domains()} >= {"software_infrastructure"}


def test_unknown_domain_is_rejected():
    with pytest.raises(ValueError, match="Unknown domain"):
        get_domain("weather")


# ---- free-form data and generic decisions -----------------------------------
def small_system() -> System:
    s = System("s", "s", parameters={"traffic_multiplier": 1.0})
    s.add_component(Component("api", "api", "gateway", entry_point=True, attributes={"capacity": 10}))
    s.add_component(Component("db", "db", "database"))
    s.add_dependency(Dependency("api->db", "api", "db", attributes={"note": "primary"}))
    return s


def test_new_fields_survive_a_round_trip_through_dicts():
    s = small_system()
    copy = System.from_dict(s.to_dict())
    assert copy.parameters == {"traffic_multiplier": 1.0}
    assert copy.dependencies[0].attributes == {"note": "primary"}
    e = Event("e", "component_failure", "db", 1, params={"cause": "disk"})
    assert Event.from_dict(e.to_dict()).params == {"cause": "disk"}


def test_set_parameter_and_set_dependency_attribute_change_only_the_copy():
    base = small_system()
    scenario = Scenario("x", "x", interventions=[
        Intervention("p", "set_parameter", {"key": "traffic_multiplier", "value": 3.0}),
        Intervention("d", "set_dependency_attribute", {"dependency_id": "api->db", "key": "note", "value": "replica"}),
    ])
    system = base.copy()
    for i in scenario.resolved_interventions():
        i.apply(system)
    assert system.parameters["traffic_multiplier"] == 3.0
    assert system.dependencies[0].attributes["note"] == "replica"
    assert base.parameters["traffic_multiplier"] == 1.0  # the original is untouched
    run_scenario(base, scenario, until=5)  # and it still runs


def test_types_are_checked_against_the_domain_registry():
    with pytest.raises(ValueError, match="unknown type"):
        Event("e", "meteor_strike", "db", 1)
    with pytest.raises(ValueError, match="unknown type"):
        Dependency("x", "a", "b", dependency_type="sometimes")


def test_scenario_runs_record_which_domain_ran_them():
    result = run_scenario(small_system(), Scenario("x", "x", events=[Event("f", "component_failure", "db", 1, 2)]), 5)
    assert result.domain == "software_infrastructure"
    assert result.metrics.downtime == 2 and result.metrics["downtime"] == 2  # both access styles
    assert result.log[-1].component_id == "api"
    assert START  # the infrastructure engine still uses the START/END/EVALUATE kinds
