"""End-to-end tests on the e-commerce example: the MVP acceptance test, minus the UI."""

from pathlib import Path

import pytest

from app.config import load_experiment_file
from app.simulation.branching import comparison_table, run_scenario
from app.simulation.metrics import time_in_status, worst_of
from app.models import Status

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "ecommerce.json"


@pytest.fixture(scope="module")
def experiment():
    return load_experiment_file(EXAMPLE)


@pytest.fixture(scope="module")
def results(experiment):
    return {s.id: run_scenario(experiment.system, s, experiment.until) for s in experiment.scenarios}


def test_baseline_is_fully_available(results):
    m = results["baseline"].metrics
    assert m.availability == 1.0 and m.affected_components == 0


def test_db_failure_takes_site_down_for_recovery_window(results):
    m = results["db-down"].metrics
    # Postgres down 5..15; gateway down 7..17 because of two 1-unit delays.
    assert m.downtime == 10
    assert m.availability == pytest.approx(1 - 10 / 30, abs=1e-4)
    assert m.affected_components == 3  # postgres, user_service, gateway (not redis)
    assert m.recovery_time == 12  # 5 -> 17


def test_cache_fallback_converts_downtime_to_degradation(results):
    m = results["db-down-cache-fallback"].metrics
    assert m.downtime == 0 and m.degraded_time == 10 and m.cost == 50


def test_replica_absorbs_the_failure(results):
    m = results["db-down-replica"].metrics
    assert m.downtime == 0 and m.degraded_time == 0 and m.affected_components == 1


def test_fast_restore_shortens_outage(results):
    assert results["db-down-fast-restore"].metrics.downtime == 3


def test_branches_do_not_mutate_base_system(experiment, results):
    assert "postgres_replica" not in experiment.system.components
    assert all(d.dependency_type != "fallback" for d in experiment.system.dependencies)


def test_children_inherit_parent_events(experiment):
    by_id = {s.id: s for s in experiment.scenarios}
    assert [e.id for e in by_id["db-down-replica"].resolved_events()] == ["db_failure"]
    assert by_id["db-down-replica"].lineage() == ["baseline", "db-down", "db-down-replica"]


def test_same_seed_and_config_reproduce_identical_logs(experiment):
    scenario = experiment.scenarios[1]
    a = run_scenario(experiment.system, scenario, experiment.until)
    b = run_scenario(experiment.system, scenario, experiment.until)
    assert a.to_dict() == b.to_dict()


def test_comparison_table_lists_every_scenario(results):
    table = comparison_table(list(results.values()))
    for r in results.values():
        assert r.scenario_name in table


def test_metric_helpers():
    tl = [(0, Status.HEALTHY), (5, Status.FAILED), (15, Status.HEALTHY)]
    assert time_in_status(tl, 30)[Status.FAILED] == 10
    merged = worst_of([tl, [(0, Status.HEALTHY), (10, Status.DEGRADED), (20, Status.HEALTHY)]])
    assert merged == [(0, Status.HEALTHY), (5, Status.FAILED), (15, Status.DEGRADED), (20, Status.HEALTHY)]
