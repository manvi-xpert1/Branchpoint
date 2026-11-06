"""Small, hand-verifiable propagation cases."""

from app.domains.infrastructure import InfrastructureRules
from app.models import Component, Dependency, Event, Status, System
from app.simulation.engine import Simulator, explain, first_change
from app.simulation.event_queue import EVALUATE, START, EventQueue, ScheduledEvent


def make_system(components, deps) -> System:
    s = System(id="t", name="t")
    for c in components:
        s.add_component(c if isinstance(c, Component) else Component(c, c, "service"))
    for d in deps:
        s.add_dependency(d)
    return s


def run(system, events, until=30, seed=0):
    sim = Simulator(system, InfrastructureRules(), until=until, seed=seed)
    sim.schedule(events)
    return sim.run(), sim


def fail(target, at=5, duration=None, **kw):
    return Event(f"fail_{target}", "component_failure", target, at, duration, **kw)


def test_event_queue_orders_by_time_then_priority_then_insertion():
    q = EventQueue()
    q.push(ScheduledEvent(5, EVALUATE, "late-eval"))
    q.push(ScheduledEvent(5, START, "start"))
    q.push(ScheduledEvent(1, EVALUATE, "early"))
    q.push(ScheduledEvent(5, EVALUATE, "late-eval-2"))
    assert [q.pop().component_id for _ in range(4)] == ["early", "start", "late-eval", "late-eval-2"]


def test_hard_dependency_chain_fails_completely():
    # A requires B requires C. Failing C fails all three.
    system = make_system("abc", [Dependency("ab", "a", "b"), Dependency("bc", "b", "c")])
    state, _ = run(system, [fail("c")])
    assert state.status == {"a": Status.FAILED, "b": Status.FAILED, "c": Status.FAILED}


def test_failure_with_duration_recovers_everything():
    system = make_system("abc", [Dependency("ab", "a", "b"), Dependency("bc", "b", "c")])
    state, _ = run(system, [fail("c", at=5, duration=10)])
    assert all(s == Status.HEALTHY for s in state.status.values())
    assert state.timeline["a"] == [(0, Status.HEALTHY), (5, Status.FAILED), (15, Status.HEALTHY)]


def test_propagation_delay_shifts_impact_in_time():
    system = make_system("ab", [Dependency("ab", "a", "b", propagation_delay=3)])
    state, _ = run(system, [fail("b", at=5)])
    assert state.timeline["a"] == [(0, Status.HEALTHY), (8, Status.FAILED)]


def test_optional_dependency_only_degrades():
    system = make_system("ab", [Dependency("ab", "a", "b", dependency_type="optional")])
    state, _ = run(system, [fail("b")])
    assert state.status["a"] == Status.DEGRADED


def test_redundant_group_survives_one_failure():
    system = make_system(
        ["app", "db", "replica"],
        [Dependency("1", "app", "db", group="data"), Dependency("2", "app", "replica", group="data")],
    )
    state, _ = run(system, [fail("db")])
    assert state.status["app"] == Status.HEALTHY

    state, _ = run(system, [fail("db"), fail("replica")])
    assert state.status["app"] == Status.FAILED


def test_fallback_keeps_component_running_degraded():
    system = make_system(
        ["svc", "db", "cache"],
        [
            Dependency("1", "svc", "db", group="data"),
            Dependency("2", "svc", "cache", dependency_type="fallback", group="data"),
        ],
    )
    state, _ = run(system, [fail("db")])
    assert state.status["svc"] == Status.DEGRADED
    # Fallback down too: no data at all.
    state, _ = run(system, [fail("db"), fail("cache")])
    assert state.status["svc"] == Status.FAILED


def test_explicit_recovery_event_restores_component():
    system = make_system("ab", [Dependency("ab", "a", "b")])
    state, _ = run(system, [fail("b"), Event("fix", "component_recovery", "b", 8)])
    assert state.timeline["a"] == [(0, Status.HEALTHY), (5, Status.FAILED), (8, Status.HEALTHY)]


def test_recovery_time_attribute_used_when_no_duration():
    b = Component("b", "b", "database", {"recovery_time": 4})
    system = make_system(["a", b], [Dependency("ab", "a", "b")])
    state, _ = run(system, [fail("b", at=5)])
    assert state.timeline["b"][-1] == (9, Status.HEALTHY)


def test_traffic_spike_degrades_or_fails_by_load():
    gw = Component("gw", "gw", "gateway", {"capacity": 100, "current_load": 60})
    system = make_system([gw], [])
    state, _ = run(system, [Event("s", "traffic_spike", "gw", 1, 5, severity=2.0)], until=3)
    assert state.status["gw"] == Status.DEGRADED  # 120 > 100
    state, _ = run(system, [Event("s", "traffic_spike", "gw", 1, 5, severity=3.0)], until=3)
    assert state.status["gw"] == Status.FAILED  # 180 > 150
    state, _ = run(system, [Event("s", "traffic_spike", "gw", 1, 5, severity=2.0)])
    assert state.status["gw"] == Status.HEALTHY  # spike over


def test_latency_increase_degrades_dependents():
    system = make_system("ab", [Dependency("ab", "a", "b")])
    state, _ = run(system, [Event("lat", "latency_increase", "b", 2, 100)])
    assert state.status == {"a": Status.DEGRADED, "b": Status.DEGRADED}


def test_every_impact_traces_back_to_its_event():
    system = make_system("abc", [Dependency("ab", "a", "b"), Dependency("bc", "b", "c")])
    state, _ = run(system, [fail("c")])
    entry = first_change(state.log, "a", Status.FAILED)
    chain = explain(state.log, entry.id)
    assert chain[0].kind == "event" and chain[0].event_id == "fail_c"
    assert [e.component_id for e in chain[1:]] == ["c", "b", "a"]


def test_cycle_does_not_loop_forever():
    system = make_system("ab", [Dependency("ab", "a", "b"), Dependency("ba", "b", "a")])
    state, _ = run(system, [fail("a", duration=5)])
    # Circular hard dependency: once both are down, neither can come back.
    assert state.status == {"a": Status.FAILED, "b": Status.FAILED}


def test_events_after_end_time_are_ignored():
    system = make_system("a", [])
    state, _ = run(system, [fail("a", at=50)], until=30)
    assert state.status["a"] == Status.HEALTHY


def test_probabilistic_events_are_reproducible_by_seed():
    system = make_system("a", [])
    events = [Event(f"e{i}", "latency_increase", "a", i, 0.5, probability=0.5) for i in range(20)]
    _, sim1 = run(system, events, seed=7)
    _, sim2 = run(system, list(reversed(events)), seed=7)
    _, sim3 = run(system, events, seed=8)
    assert sim1.skipped_events == sim2.skipped_events
    assert sim1.skipped_events != sim3.skipped_events
    assert 0 < len(sim1.skipped_events) < 20
