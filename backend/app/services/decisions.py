"""Use cases for the decision layer: objectives, evaluating futures, sensitivity.

Evaluations are computed live from simulation runs (each scenario with its
own seed, or a Monte Carlo batch), so every number shown comes from actual
execution. They are not stored: re-running with the same inputs and seeds
gives the same result.
"""

from __future__ import annotations

import time

from sqlalchemy.orm import Session

from ..database import SystemRow
from ..decision import DecisionModel, Future, default_model, evaluate, find_inputs, insights, sensitivity
from ..domains.registry import get_domain
from ..schemas import (DecisionModelIn, DecisionModelOut, EvaluateRequest, EvaluationOut, FutureOut,
                       InsightOut, SensitivityOut, SensitivityRequest, SensitivityRowOut)
from ..simulation.branching import run_scenario
from ..simulation.engine import SimulationError
from ..simulation.montecarlo import run_monte_carlo
from . import scenarios, systems
from .errors import InvalidInput

# One request may run at most this many simulations, so a single click cannot tie up the server.
MAX_SIMULATIONS = 10_000


# ---- objectives ---------------------------------------------------------------
def model_for(row: SystemRow) -> tuple[DecisionModel, bool]:
    """The saved decision model, or the domain's defaults (second value True)."""
    if row.objectives:
        return DecisionModel.from_dict(row.objectives), False
    return default_model(get_domain(row.domain).spec), True


def _to_model(data: DecisionModelIn, domain: str) -> DecisionModel:
    model = DecisionModel.from_dict(data.model_dump())
    problems = model.errors(get_domain(domain).spec)
    if not model.objectives:
        problems.append("add at least one objective")
    if problems:
        raise InvalidInput("; ".join(problems))
    return model


def get_objectives(db: Session, system_id: str) -> DecisionModelOut:
    model, is_default = model_for(systems.get(db, system_id))
    return DecisionModelOut(**model.to_dict(), is_default=is_default)


def set_objectives(db: Session, system_id: str, data: DecisionModelIn | None) -> DecisionModelOut:
    """Save a decision model; ``None`` (or an empty body) resets to the domain defaults."""
    row = systems.get(db, system_id)
    if data is None or (not data.objectives and not data.constraints):
        row.objectives = {}
    else:
        row.objectives = _to_model(data, row.domain).to_dict()
    db.commit()
    return get_objectives(db, system_id)


# ---- evaluation ---------------------------------------------------------------
def _baseline(rows, requested: str | None) -> str | None:
    """The requested baseline, or the scenario every other one branches from."""
    ids = {r.id for r in rows}
    if requested:
        if requested not in ids:
            raise InvalidInput(f"baseline {requested!r} is not one of the evaluated scenarios")
        return requested
    for r in rows:
        if all(o.id == r.id or _descends_from(o, r.id) for o in rows):
            return r.id
    return None


def _descends_from(row, ancestor_id: str) -> bool:
    cur = row.parent
    while cur is not None:
        if cur.id == ancestor_id:
            return True
        cur = cur.parent
    return False


def evaluate_system(db: Session, system_id: str, req: EvaluateRequest) -> EvaluationOut:
    row = systems.get(db, system_id)
    spec = get_domain(row.domain).spec
    model = _to_model(req.model, row.domain) if req.model else model_for(row)[0]

    if req.scenario_ids is None:
        scenario_rows = list(row.scenarios)
    else:
        scenario_rows = [scenarios.get(db, sid) for sid in dict.fromkeys(req.scenario_ids)]
        foreign = [s.id for s in scenario_rows if s.system_id != row.id]
        if foreign:
            raise InvalidInput(f"scenarios {foreign} belong to another system")
    if not scenario_rows:
        raise InvalidInput("this system has no scenarios to evaluate")
    baseline_id = _baseline(scenario_rows, req.baseline_id)
    total = req.runs * len(scenario_rows)
    if total > MAX_SIMULATIONS:
        raise InvalidInput(f"That is {total:,} simulations ({req.runs} runs x {len(scenario_rows)} futures); "
                           f"the limit per request is {MAX_SIMULATIONS:,}. Use fewer runs or futures.")

    started = time.perf_counter()
    system = systems.to_domain(row)
    futures, mc = [], {}
    try:
        for s_row in scenario_rows:
            scenario = scenarios.to_domain(s_row)
            if req.runs == 1:
                result = run_scenario(system, scenario, req.until)
                futures.append(Future(s_row.id, s_row.name, dict(result.metrics)))
            else:
                batch = run_monte_carlo(system, scenario, req.until, req.runs, req.base_seed)
                samples = [dict(s.metrics) for s in batch.samples]
                futures.append(Future(s_row.id, s_row.name, {}, samples))
                mc[s_row.id] = batch.to_dict()
        ev = evaluate(futures, spec, model)
    except (SimulationError, ValueError, KeyError) as exc:
        raise InvalidInput(f"Evaluation failed: {exc}") from exc
    found = insights(ev, spec, baseline_id=baseline_id, montecarlo=mc)
    elapsed_ms = (time.perf_counter() - started) * 1000

    by_id = {f.id: f for f in futures}
    out = []
    for f in ev.futures:
        source = by_id[f.id]
        summary = mc.get(f.id)
        out.append(FutureOut(
            id=f.id, name=f.name, rank=f.rank, score=f.score, feasible=f.feasible, pareto=f.pareto,
            dominated_by=f.dominated_by, values=f.values,
            metrics={m.key: source.value(m.key) for m in spec.metrics},
            constraints=[c.__dict__ for c in f.constraints],
            objectives=[o.__dict__ for o in f.objectives],
            stats=summary["metric_stats"] if summary else None,
            risk=summary["risk"] if summary else None,
            drivers=summary["drivers"] if summary else [],
        ))
    return EvaluationOut(
        system_id=row.id, domain=spec.name, until=req.until, runs=req.runs,
        model=DecisionModelIn(**model.to_dict()), futures=out,
        skipped_objectives=ev.skipped_objectives, recommended=ev.recommended, robust=ev.robust,
        weight_flips=ev.weight_flips, baseline_id=baseline_id,
        insights=[InsightOut(**i.__dict__) for i in found], elapsed_ms=round(elapsed_ms, 3),
    )


# ---- sensitivity --------------------------------------------------------------
def sensitivity_for(db: Session, scenario_id: str, req: SensitivityRequest) -> SensitivityOut:
    s_row = scenarios.get(db, scenario_id)
    spec = get_domain(s_row.system.domain).spec
    metric = req.metric or spec.risk_metric
    if metric not in {m.key for m in spec.metrics}:
        raise InvalidInput(f"unknown metric {metric!r}")
    system_row = s_row.system
    inputs = len(find_inputs(systems.to_domain(system_row), scenarios.to_domain(s_row)))
    total = (2 * min(inputs, 60) + 1) * req.runs
    if total > MAX_SIMULATIONS:
        raise InvalidInput(f"Sensitivity would need {total:,} simulations ({inputs} inputs x 2 x {req.runs} runs); "
                           f"the limit is {MAX_SIMULATIONS:,}. Use fewer runs per point.")
    started = time.perf_counter()
    try:
        result = sensitivity(systems.to_domain(s_row.system), scenarios.to_domain(s_row), req.until,
                             metric, req.delta, req.runs)
    except (SimulationError, ValueError, KeyError) as exc:
        raise InvalidInput(f"Sensitivity analysis failed: {exc}") from exc
    return SensitivityOut(
        scenario_id=s_row.id, metric=metric, baseline=result.baseline, delta=result.delta, runs=result.runs,
        rows=[SensitivityRowOut(id=r.input.id, kind=r.input.kind, target=r.input.target, key=r.input.key,
                                value=r.input.value, low_value=r.low_value, high_value=r.high_value,
                                low=r.low, high=r.high, swing=r.swing) for r in result.rows],
        elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
    )
