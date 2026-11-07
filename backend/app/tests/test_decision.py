"""Decision layer: objectives, constraints, scoring, Pareto sets, robustness, insights, sensitivity.

The futures below are made-up metric values (not simulation output) so
every score can be checked by hand:

    A: downtime 0,  cost 300, availability 1.0
    B: downtime 10, cost 0,   availability 0.667
    C: downtime 10, cost 50,  availability 0.667
"""

import pytest

from app.decision import (Constraint, DecisionModel, Future, Objective, default_model, evaluate,
                          find_inputs, insights, sensitivity)
from app.domains.registry import get_domain
from app.models import Component, Dependency, Event, System
from app.simulation.branching import Scenario
from app.simulation.montecarlo import run_monte_carlo

SPEC = get_domain("software_infrastructure").spec


def futures():
    return [
        Future("a", "A", {"downtime": 0, "cost": 300, "availability": 1.0}),
        Future("b", "B", {"downtime": 10, "cost": 0, "availability": 0.667}),
        Future("c", "C", {"downtime": 10, "cost": 50, "availability": 0.667}),
    ]


def model(downtime=1.0, cost=1.0, constraints=()):
    return DecisionModel([Objective("downtime", downtime), Objective("cost", cost)], list(constraints))


# ---- scoring ------------------------------------------------------------------
def test_min_max_scores_and_weighted_score():
    ev = evaluate(futures(), SPEC, model())
    c = ev.by_id("c")
    assert [round(s.score, 4) for s in c.objectives] == [0, round(250 / 300, 4)]
    assert c.score == pytest.approx((0 + 250 / 300) / 2, abs=1e-6)
    assert ev.by_id("a").score == ev.by_id("b").score == 0.5
    assert [f.id for f in ev.futures] == ["a", "b", "c"]  # A and B tie; names break ties


def test_weights_change_the_ranking():
    ev = evaluate(futures(), SPEC, model(downtime=3))
    assert ev.by_id("a").score == 0.75 and ev.recommended == "a"
    ev = evaluate(futures(), SPEC, model(cost=3))
    assert ev.recommended == "b"


def test_direction_comes_from_the_catalog_and_can_be_overridden():
    m = DecisionModel([Objective("availability", 1)])
    assert evaluate(futures(), SPEC, m).recommended == "a"  # higher is better
    m = DecisionModel([Objective("availability", 1, direction="minimize")])
    assert evaluate(futures(), SPEC, m).recommended in {"b", "c"}


def test_equal_values_score_one_for_everyone():
    same = [Future("x", "X", {"downtime": 5}), Future("y", "Y", {"downtime": 5})]
    ev = evaluate(same, SPEC, DecisionModel([Objective("downtime", 1)]))
    assert [f.score for f in ev.futures] == [1.0, 1.0]


def test_missing_values_score_zero_and_objectives_without_any_data_are_skipped():
    fs = [Future("x", "X", {"downtime": 1, "recovery_time": None, "mean_latency": None}),
          Future("y", "Y", {"downtime": 2, "recovery_time": 5, "mean_latency": None})]
    m = DecisionModel([Objective("downtime", 1), Objective("recovery_time", 1), Objective("mean_latency", 1)])
    ev = evaluate(fs, SPEC, m)
    assert ev.skipped_objectives == ["mean_latency"]
    assert [s.score for s in ev.by_id("x").objectives] == [1.0, 0.0]  # never recovered = worst
    assert ev.by_id("x").score == ev.by_id("y").score == 0.5


# ---- constraints --------------------------------------------------------------
def test_infeasible_futures_rank_after_feasible_ones():
    ev = evaluate(futures(), SPEC, model(cost=10, constraints=[Constraint("availability", ">=", 0.9)]))
    assert ev.by_id("b").score > ev.by_id("a").score  # B is cheaper and cost matters most...
    assert [f.id for f in ev.futures][0] == "a"         # ...but B breaks the constraint
    assert ev.recommended == "a"
    check = ev.by_id("b").constraints[0]
    assert (check.satisfied, check.value, check.description) == (False, 0.667, "Availability >= 90.0%")


def test_no_recommendation_when_nothing_is_feasible():
    ev = evaluate(futures(), SPEC, model(constraints=[Constraint("downtime", "<", 0)]))
    assert ev.recommended is None and not any(f.feasible for f in ev.futures)


def test_chance_constraints_use_the_share_of_runs():
    samples = [{"downtime": 0}, {"downtime": 0}, {"downtime": 10}, {"downtime": 0}]
    f = Future("x", "X", {}, samples=samples)
    plain = evaluate([f], SPEC, DecisionModel([Objective("downtime")], [Constraint("downtime", "<=", 5)]))
    assert plain.futures[0].values["downtime"] == 2.5 and plain.futures[0].feasible
    assert plain.futures[0].constraints[0].satisfied_share == 0.75
    chance = evaluate([f], SPEC, DecisionModel([Objective("downtime")],
                                               [Constraint("downtime", "<=", 5, confidence=0.8)]))
    assert not chance.futures[0].feasible


def test_invalid_models_are_rejected():
    for bad in (DecisionModel([Objective("happiness")]), DecisionModel([Objective("downtime", -1)]),
                DecisionModel([Objective("downtime", 0)]),
                DecisionModel([Objective("downtime")], [Constraint("downtime", "~", 1)])):
        with pytest.raises(ValueError):
            evaluate(futures(), SPEC, bad)


def test_default_model_and_round_trip():
    m = default_model(SPEC)
    assert m.objectives[0].metric == "downtime" and m.objectives[0].weight == 3
    m.constraints.append(Constraint("availability", ">=", 0.99, confidence=0.9))
    assert DecisionModel.from_dict(m.to_dict()) == m


# ---- Pareto and robustness ----------------------------------------------------
def test_pareto_front():
    ev = evaluate(futures(), SPEC, model())
    assert {f.id for f in ev.futures if f.pareto} == {"a", "b"}
    assert ev.by_id("c").dominated_by == ["b"]  # same downtime as B but costs more


def test_robustness_detects_a_winner_that_depends_on_the_weights():
    ev = evaluate(futures(), SPEC, model(downtime=1.2))  # A wins narrowly: 0.545 vs 0.455
    assert ev.recommended == "a" and ev.robust is False
    assert {"metric": "downtime", "factor": 0.5, "winner": "b"} in ev.weight_flips
    assert evaluate(futures(), SPEC, model(downtime=3)).robust is True


# ---- insights -----------------------------------------------------------------
def test_insights_are_built_from_the_numbers():
    ev = evaluate(futures(), SPEC, model(downtime=3, constraints=[Constraint("availability", ">=", 0.9)]))
    found = insights(ev, SPEC, baseline_id="b")
    text = {}
    for i in found:
        text[i.kind] = text.get(i.kind, "") + i.text + " | "
    assert text["recommendation"].removesuffix(" | ") == "A ranks first with a score of 75/100: best on downtime."
    assert "C is dominated by B" in text["dominated"]
    assert "B breaks “Availability >= 90.0%”: 66.7%" in text["constraint"]
    assert "downtime 10 → 0" in text["opportunity"]
    assert "robust" in text["robustness"]


def test_insights_explain_why_there_is_no_recommendation():
    ev = evaluate(futures(), SPEC, model(constraints=[Constraint("availability", ">=", 1.1)]))
    first = insights(ev, SPEC)[0]
    assert first.kind == "constraint" and first.text.startswith("No future meets every constraint")


def flaky_system() -> tuple[System, Scenario]:
    s = System("s", "s")
    s.add_component(Component("api", "api", "service", entry_point=True))
    s.add_component(Component("db", "db", "database", attributes={"recovery_time": 10, "capacity": 100}))
    s.add_dependency(Dependency("api->db", "api", "db"))
    return s, Scenario("x", "x", events=[Event("outage", "component_failure", "db", 2, probability=0.5)])


def test_monte_carlo_risk_summary_and_drivers():
    system, scenario = flaky_system()
    mc = run_monte_carlo(system, scenario, until=30, runs=200)
    assert mc.metric_stats["downtime"].mean == mc.aggregates.downtime_mean
    driver = mc.drivers[0]
    assert (driver.event_id, driver.mean_if_occurred, driver.mean_if_not) == ("outage", 10, 0)
    assert mc.risk.worst_5_percent_mean == 10 and mc.risk.p_nonzero == driver.frequency
    found = insights(evaluate([Future("x", "x", {}, [dict(s.metrics) for s in mc.samples])], SPEC,
                              DecisionModel([Objective("downtime")])), SPEC, montecarlo={"x": mc.to_dict()})
    assert any(i.kind == "risk" and "outage drives the most risk" in i.text for i in found)


# ---- sensitivity --------------------------------------------------------------
def test_sensitivity_ranks_inputs_by_swing():
    system, scenario = flaky_system()
    scenario.events[0].probability = 1.0
    result = sensitivity(system, scenario, until=30, metric="downtime")
    assert result.baseline == 10
    top = result.rows[0]
    assert top.input.id == "attribute:db:recovery_time"
    assert (top.low, top.high, top.swing) == (8, 12, 4)  # recovery time 8 and 12
    assert next(r for r in result.rows if r.input.key == "capacity").swing == 0


def test_find_inputs_skips_zero_and_non_numeric_values():
    system, scenario = flaky_system()
    system.components["api"].attributes.update({"note": "x", "current_load": 0, "flag": True})
    ids = {i.id for i in find_inputs(system, scenario)}
    assert ids == {"attribute:db:recovery_time", "attribute:db:capacity", "event:outage:probability"}
