"""Monte Carlo: many seeded runs of one scenario, summarised as a distribution."""

import pytest

from app.models import Component, Dependency, Event, System
from app.simulation.branching import Scenario
from app.simulation.montecarlo import percentile, run_monte_carlo


def two_tier() -> System:
    """api requires db. api is the entry point, so db failing is downtime."""
    s = System(id="t", name="t")
    s.add_component(Component("api", "api", "gateway", entry_point=True))
    s.add_component(Component("db", "db", "database"))
    s.add_dependency(Dependency("api->db", "api", "db"))
    return s


def db_outage(probability: float) -> Scenario:
    # db fails at t=5 for 10 time units. If it happens, downtime is exactly 10.
    event = Event("db_fail", "component_failure", "db", 5, 10, probability=probability)
    return Scenario(id="s", name="s", events=[event])


# ---- percentile -------------------------------------------------------
def test_percentile_interpolates_between_sorted_values():
    values = [10, 0, 30, 20]  # sorted: 0, 10, 20, 30
    assert percentile(values, 0) == 0
    assert percentile(values, 50) == 15  # halfway between 10 and 20
    assert percentile(values, 100) == 30
    assert percentile([7], 95) == 7


def test_percentile_rejects_empty_input():
    with pytest.raises(ValueError):
        percentile([], 50)


# ---- engine -----------------------------------------------------------
def test_deterministic_scenario_gives_identical_runs():
    result = run_monte_carlo(two_tier(), db_outage(1.0), until=30, runs=20, base_seed=1)
    assert result.deterministic
    assert {r.metrics.downtime for r in result.samples} == {10}
    agg = result.aggregates
    assert agg.downtime_mean == agg.downtime_p50 == agg.downtime_p95 == agg.downtime_max == 10
    assert agg.p_any_downtime == 1.0
    assert agg.event_frequency == {"db_fail": 1.0}


def test_run_i_uses_seed_base_plus_i():
    result = run_monte_carlo(two_tier(), db_outage(0.5), until=30, runs=5, base_seed=100)
    assert [r.seed for r in result.samples] == [100, 101, 102, 103, 104]


def test_half_probability_event_occurs_about_half_the_time():
    result = run_monte_carlo(two_tier(), db_outage(0.5), until=30, runs=1000, base_seed=0)
    agg = result.aggregates
    assert not result.deterministic
    # Binomial(1000, 0.5) has a standard deviation of about 16, so 0.05
    # (50 runs) is roughly a 3-sigma tolerance.
    assert agg.event_frequency["db_fail"] == pytest.approx(0.5, abs=0.05)
    # Every run is either 0 or 10 downtime, so these must line up.
    assert agg.p_any_downtime == agg.event_frequency["db_fail"]
    assert agg.downtime_mean == pytest.approx(10 * agg.p_any_downtime)
    assert agg.downtime_max == 10
    # Each run's availability is rounded to 4 decimals in compute_metrics,
    # so the mean can be off by up to 0.00005.
    assert agg.availability_mean == pytest.approx(1 - agg.downtime_mean / 30, abs=1e-4)


def test_same_base_seed_gives_identical_aggregates():
    a = run_monte_carlo(two_tier(), db_outage(0.3), until=30, runs=200, base_seed=7)
    b = run_monte_carlo(two_tier(), db_outage(0.3), until=30, runs=200, base_seed=7)
    assert a.aggregates == b.aggregates
    assert [r.metrics for r in a.samples] == [r.metrics for r in b.samples]


def test_different_base_seed_changes_the_sample():
    a = run_monte_carlo(two_tier(), db_outage(0.3), until=30, runs=200, base_seed=7)
    b = run_monte_carlo(two_tier(), db_outage(0.3), until=30, runs=200, base_seed=8)
    assert [r.occurred for r in a.samples] != [r.occurred for r in b.samples]


def test_base_seed_defaults_to_the_scenario_seed():
    scenario = db_outage(0.5)
    scenario.seed = 55
    result = run_monte_carlo(two_tier(), scenario, until=30, runs=3)
    assert result.base_seed == 55 and result.samples[0].seed == 55


def test_monte_carlo_does_not_modify_the_inputs():
    system, scenario = two_tier(), db_outage(0.5)
    before = (system.to_dict(), scenario.seed)
    run_monte_carlo(system, scenario, until=30, runs=10, base_seed=3)
    assert (system.to_dict(), scenario.seed) == before


def test_runs_must_be_positive():
    with pytest.raises(ValueError):
        run_monte_carlo(two_tier(), db_outage(0.5), until=30, runs=0)


def test_summary_is_json_friendly_and_keeps_per_run_downtimes():
    result = run_monte_carlo(two_tier(), db_outage(0.5), until=30, runs=10, base_seed=0)
    summary = result.to_dict()
    assert summary["runs"] == 10
    assert len(summary["downtimes"]) == 10
    assert set(summary["downtimes"]) <= {0, 10}
    assert "samples" not in summary  # full per-run results are not stored
