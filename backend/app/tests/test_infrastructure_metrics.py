"""Opt-in infrastructure modelling: load flow, latency, utilisation and cost (Phase 3).

Every case is small enough to check by hand. The base chain is

    gw (entry) --requires--> api --requires--> db

with latencies 5 + 20 + 15 = 40 ms when everything is healthy.
"""

import pytest

from app.models import Component, Dependency, Event, Status, System
from app.simulation.branching import Intervention, Scenario, comparison_table, run_scenario
from app.simulation.engine import explain


def chain(share_api=None, share_db=None, **params) -> System:
    s = System("s", "s", parameters=params)
    s.add_component(Component("gw", "gw", "gateway", entry_point=True,
                              attributes={"capacity": 100, "current_load": 50, "latency": 5}))
    s.add_component(Component("api", "api", "service",
                              attributes={"capacity": 100, "current_load": 50, "latency": 20}))
    s.add_component(Component("db", "db", "database",
                              attributes={"capacity": 100, "current_load": 10, "latency": 15}))
    s.add_dependency(Dependency("gw->api", "gw", "api",
                                attributes={} if share_api is None else {"load_share": share_api}))
    s.add_dependency(Dependency("api->db", "api", "db",
                                attributes={} if share_db is None else {"load_share": share_db}))
    return s


def run(system, *events, until=10, interventions=()):
    return run_scenario(system, Scenario("x", "x", events=list(events), interventions=list(interventions)), until)


SPIKE = Event("spike", "traffic_spike", "gw", 1, 4, severity=3)  # gw load 50 -> 150 for t in [1, 5)


# ---- load flow ----------------------------------------------------------------
def test_without_load_share_a_spike_stays_on_its_target():
    r = run(chain(), SPIKE)
    tl = r.timelines
    assert tl["gw"] == [(0, Status.HEALTHY), (1, Status.DEGRADED), (5, Status.HEALTHY)]
    assert tl["api"] == [(0, Status.HEALTHY)]
    assert r.state.load["api"] == [(0, 50)]
    assert r.metrics.peak_utilisation == 1.5  # gw: 150 / 100


def test_load_share_forwards_the_extra_load_downstream():
    r = run(chain(share_api=1.0), SPIKE)
    # gw's extra load is +100, so api goes 50 -> 150 (> capacity 100, not > 150): degraded.
    assert r.state.load["api"] == [(0, 50), (1, 150), (5, 50)]
    api_change = next(e for e in r.log if e.kind == "status_change" and e.component_id == "api")
    assert (api_change.time, api_change.new_status) == (1, Status.DEGRADED)
    # The change is explained by the load arriving from gw, caused by the spike.
    chain_msgs = [e.message for e in explain(r.log, api_change.id)]
    assert chain_msgs[0] == "traffic spike begins" and "load from callers +100" in chain_msgs[1]
    assert r.timelines["api"][-1] == (5, Status.HEALTHY)


def test_load_share_is_a_fraction_and_chains_through_several_hops():
    r = run(chain(share_api=0.4, share_db=0.5), SPIKE)
    assert r.state.load["api"][1] == (1, 90)   # 50 + 100 x 0.4: still under capacity
    assert r.state.load["db"][1] == (1, 30)    # 10 + 40 x 0.5
    assert r.timelines["api"] == [(0, Status.HEALTHY)]
    assert r.metrics.peak_utilisation == 1.5


def test_forwarded_load_can_overload_and_fail_a_dependency():
    s = chain(share_api=2.0)  # every extra request at gw makes two at api
    r = run(s, SPIKE)
    # api: 50 + 200 = 250 > 100 x 1.5, so api fails, and gw (requires api) fails with it.
    assert Status.FAILED in [st for _, st in r.timelines["api"]]
    assert r.metrics.downtime == 4


# ---- latency ------------------------------------------------------------------
def test_latency_is_the_sum_along_the_call_path():
    r = run(chain())
    assert (r.metrics.mean_latency, r.metrics.peak_latency) == (40, 40)
    assert r.series["latency"]["entry points"] == [[0, 40]]


def test_only_the_component_that_is_slow_itself_gets_the_slowdown():
    # db is degraded for 4 of 10 time units; its callers are degraded too, but only db is slower.
    r = run(chain(), Event("slow", "latency_increase", "db", 2, 4))
    assert r.metrics.peak_latency == 5 + 20 + 15 * 3  # 70, not 3x everything
    assert r.metrics.mean_latency == pytest.approx((6 * 40 + 4 * 70) / 10)


def test_degraded_factor_and_sla_are_system_parameters():
    r = run(chain(degraded_latency_factor=2, latency_sla=50), Event("slow", "latency_increase", "db", 2, 4))
    assert r.metrics.peak_latency == 55
    assert r.metrics.sla_breach_time == 4


def test_downtime_counts_as_an_sla_breach_and_is_left_out_of_mean_latency():
    r = run(chain(latency_sla=100), Event("down", "component_failure", "db", 2, 3))
    assert r.metrics.mean_latency == 40   # averaged over the 7 units it was serving
    assert r.metrics.sla_breach_time == 3
    assert [2, None] in r.series["latency"]["entry points"]


def test_a_replica_in_the_same_group_takes_over_with_its_own_latency():
    s = chain()
    s.dependencies[1].group = "data"
    s.add_component(Component("db2", "db2", "database", attributes={"latency": 30}))
    s.add_dependency(Dependency("api->db2", "api", "db2", group="data"))
    r = run(s, Event("down", "component_failure", "db", 2, 3))
    assert r.metrics.downtime == 0
    assert r.metrics.peak_latency == 5 + 20 + 30   # the healthy, slower replica
    assert r.series["latency"]["entry points"][0] == [0, 40]  # the faster primary when both are up


def test_a_failed_optional_dependency_adds_no_latency():
    s = chain()
    s.add_component(Component("cache", "cache", "cache", attributes={"latency": 2}))
    s.add_dependency(Dependency("api->cache", "api", "cache", dependency_type="optional"))
    r = run(s, Event("down", "component_failure", "cache", 5, 5))
    assert r.series["latency"]["entry points"] == [[0, 42], [5, 40]]


def test_latency_metrics_are_absent_without_latency_data():
    s = System("s", "s")
    s.add_component(Component("a", "a", "service", entry_point=True))
    m = run(s).metrics
    assert m.mean_latency is None and m.sla_breach_time is None and m.peak_utilisation is None
    assert "latency" not in run(s).series


# ---- cost ---------------------------------------------------------------------
def test_running_cost_and_total_cost():
    s = chain()
    s.components["api"].attributes["cost_per_time"] = 2
    s.components["db"].attributes["cost_per_time"] = 1
    r = run(s, interventions=[Intervention("i", "set_attribute",
                                           {"component_id": "db", "key": "capacity", "value": 200}, cost=50)])
    assert (r.metrics.cost, r.metrics.running_cost, r.metrics.total_cost) == (50, 30, 80)
    assert run(chain()).metrics.running_cost is None


def test_comparison_table_hides_metrics_nobody_has():
    s = System("s", "s")
    s.add_component(Component("a", "a", "service", entry_point=True))
    table = comparison_table([run(s)])
    assert "Availability" in table and "Mean latency" not in table and "Running cost" not in table
