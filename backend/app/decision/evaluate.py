"""Score, rank and compare alternative futures against a decision model.

Given several futures (one per scenario), each with its metrics (and,
optionally, the per-run metrics of a Monte Carlo batch):

1. **Constraints.** Each constraint is checked on the future's value (the
   mean over runs when there are samples). With samples we also report the
   share of runs that satisfy it; a chance constraint (``confidence``)
   uses that share. A future that breaks any constraint is infeasible.
2. **Normalised scores.** For each objective, values are rescaled across
   the futures being compared: the best value scores 1, the worst 0
   (min-max normalisation). A missing value (None) scores 0. If every
   future has the same value the objective scores 1 for all of them and
   cannot change the ranking.
3. **Weighted score** = sum(weight x score) / sum(weights), from 0 to 1.
   It is *relative*: it only means something within this comparison.
4. **Rank**: feasible futures first, by weighted score.
5. **Pareto set**: a future is *dominated* if another one is at least as
   good on every objective and strictly better on at least one. Futures
   no one dominates form the Pareto set: every one of them is a defensible
   choice, depending on how you weigh the objectives.
6. **Weight robustness**: does the winner change if any single weight is
   halved or doubled? This tells you how much the recommendation depends
   on the exact weights.

Pure: no database, no web framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from ..domains.spec import DomainSpec
from .model import Constraint, DecisionModel, Objective


@dataclass
class Future:
    id: str
    name: str
    metrics: dict[str, Any]
    samples: list[dict[str, Any]] | None = None  # per-run metrics from Monte Carlo

    def value(self, metric: str) -> float | None:
        """The metric's value: the mean over runs when samples exist."""
        if self.samples:
            present = [s.get(metric) for s in self.samples if s.get(metric) is not None]
            return sum(present) / len(present) if present else None
        return self.metrics.get(metric)


@dataclass
class ConstraintCheck:
    metric: str
    description: str
    value: float | None
    satisfied: bool
    satisfied_share: float | None = None  # share of runs that satisfy it (with samples)


@dataclass
class ObjectiveScore:
    metric: str
    value: float | None
    score: float  # 0 (worst in this comparison) .. 1 (best)
    weight: float
    contribution: float  # weight x score / total weight


@dataclass
class FutureEvaluation:
    id: str
    name: str
    values: dict[str, float | None]
    feasible: bool
    constraints: list[ConstraintCheck]
    objectives: list[ObjectiveScore]
    score: float
    rank: int = 0
    pareto: bool = False
    dominated_by: list[str] = field(default_factory=list)


@dataclass
class Evaluation:
    futures: list[FutureEvaluation]  # in rank order
    objectives: list[Objective]  # the active ones (others had no data)
    skipped_objectives: list[str]  # objectives with no value in any future
    constraints: list[Constraint]
    recommended: str | None  # id of the best feasible future
    robust: bool | None  # winner unchanged by halving/doubling any one weight
    weight_flips: list[dict[str, Any]]  # weight changes that would change the winner

    def by_id(self, future_id: str) -> FutureEvaluation:
        return next(f for f in self.futures if f.id == future_id)


def _utility(value: float | None, direction: str) -> float | None:
    """Turn a value into "higher is better" so all comparisons go one way."""
    if value is None:
        return None
    return value if direction == "maximize" else -value


def check_constraints(future: Future, constraints: list[Constraint], spec: DomainSpec) -> list[ConstraintCheck]:
    checks = []
    for c in constraints:
        value = future.value(c.metric)
        share = None
        if future.samples:
            share = sum(1 for s in future.samples if c.holds(s.get(c.metric))) / len(future.samples)
        satisfied = (share >= c.confidence) if (c.confidence is not None and share is not None) else c.holds(value)
        checks.append(ConstraintCheck(c.metric, c.describe(spec), value, satisfied, share))
    return checks


def _rank_order(futures: list[FutureEvaluation]) -> list[FutureEvaluation]:
    return sorted(futures, key=lambda f: (not f.feasible, -f.score, f.name))


def _score(futures: list[Future], objectives: list[Objective], spec: DomainSpec,
           values: dict[str, dict[str, float | None]]) -> dict[str, list[ObjectiveScore]]:
    total_weight = sum(o.weight for o in objectives) or 1.0
    out: dict[str, list[ObjectiveScore]] = {f.id: [] for f in futures}
    for o in objectives:
        direction = o.resolved_direction(spec)
        utils = {f.id: _utility(values[f.id][o.metric], direction) for f in futures}
        present = [u for u in utils.values() if u is not None]
        best, worst = max(present), min(present)
        for f in futures:
            u = utils[f.id]
            if u is None:
                s = 0.0
            elif best == worst:
                s = 1.0
            else:
                s = (u - worst) / (best - worst)
            out[f.id].append(ObjectiveScore(o.metric, values[f.id][o.metric], s, o.weight,
                                            o.weight * s / total_weight))
    return out


def pareto_front(futures: list[Future], objectives: list[Objective], spec: DomainSpec,
                 values: dict[str, dict[str, float | None]]) -> dict[str, list[str]]:
    """future id -> ids of the futures that dominate it (empty list: on the Pareto front)."""
    directions = {o.metric: o.resolved_direction(spec) for o in objectives if o.weight > 0}
    neg_inf = float("-inf")

    def utils(fid: str) -> list[float]:
        return [u if (u := _utility(values[fid][m], d)) is not None else neg_inf for m, d in directions.items()]

    table = {f.id: utils(f.id) for f in futures}
    dominated: dict[str, list[str]] = {f.id: [] for f in futures}
    for a in futures:
        for b in futures:
            if a.id == b.id:
                continue
            ua, ub = table[a.id], table[b.id]
            if all(x >= y for x, y in zip(ua, ub)) and any(x > y for x, y in zip(ua, ub)):
                dominated[b.id].append(a.id)
    return dominated


def evaluate(futures: list[Future], spec: DomainSpec, model: DecisionModel,
             check_robustness: bool = True) -> Evaluation:
    if not futures:
        raise ValueError("nothing to evaluate")
    problems = model.errors(spec)
    if problems:
        raise ValueError("; ".join(problems))

    keys = {o.metric for o in model.objectives} | {c.metric for c in model.constraints}
    values = {f.id: {k: f.value(k) for k in keys} for f in futures}
    active = [o for o in model.objectives if o.weight > 0 and any(values[f.id][o.metric] is not None for f in futures)]
    skipped = [o.metric for o in model.objectives if o.weight > 0 and o not in active]

    scores = _score(futures, active, spec, values) if active else {f.id: [] for f in futures}
    dominated = pareto_front(futures, active, spec, values) if active else {f.id: [] for f in futures}

    evaluated = []
    for f in futures:
        checks = check_constraints(f, model.constraints, spec)
        evaluated.append(FutureEvaluation(
            id=f.id, name=f.name,
            values={k: values[f.id][k] for k in keys},
            feasible=all(c.satisfied for c in checks),
            constraints=checks,
            objectives=scores[f.id],
            score=round(sum(s.contribution for s in scores[f.id]), 6),
            pareto=not dominated[f.id],
            dominated_by=dominated[f.id],
        ))
    ranked = _rank_order(evaluated)
    for i, f in enumerate(ranked, start=1):
        f.rank = i
    recommended = ranked[0].id if ranked[0].feasible else None

    robust, flips = None, []
    if check_robustness and recommended and len(active) > 1 and len(futures) > 1:
        for o in active:
            for factor in (0.5, 2.0):
                changed = DecisionModel(
                    objectives=[replace(x, weight=x.weight * factor) if x is o else x for x in model.objectives],
                    constraints=model.constraints,
                )
                winner = evaluate(futures, spec, changed, check_robustness=False).recommended
                if winner != recommended:
                    flips.append({"metric": o.metric, "factor": factor, "winner": winner})
        robust = not flips

    return Evaluation(
        futures=ranked, objectives=active, skipped_objectives=skipped, constraints=list(model.constraints),
        recommended=recommended, robust=robust, weight_flips=flips,
    )
