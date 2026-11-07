"""Plain-language insights derived from an evaluation (and optional Monte Carlo summaries).

Every sentence is generated from numbers that were computed by the
simulation and the evaluation; nothing is written by hand or guessed.
Each insight keeps references to the futures and metrics it is about,
so the UI can link it to the evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..domains.spec import DomainSpec, format_value
from .evaluate import Evaluation, FutureEvaluation

Kind = Literal["recommendation", "tradeoff", "dominated", "constraint", "risk", "robustness", "opportunity"]


@dataclass
class Insight:
    kind: Kind
    text: str
    future_ids: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)


def _fmt(spec: DomainSpec, metric: str, value: Any) -> str:
    return format_value(spec.metric(metric), value)


def _label(spec: DomainSpec, metric: str) -> str:
    return spec.metric(metric).label.lower()


def _best_on(f: FutureEvaluation) -> list[str]:
    return [s.metric for s in f.objectives if s.score == 1.0 and s.value is not None]


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def insights(ev: Evaluation, spec: DomainSpec, baseline_id: str | None = None,
             montecarlo: dict[str, dict[str, Any]] | None = None) -> list[Insight]:
    """Build insights. ``montecarlo`` maps future id -> MonteCarloResult.to_dict()."""
    out: list[Insight] = []
    names = {f.id: f.name for f in ev.futures}
    top = ev.futures[0]

    # 1. Recommendation, or why there is none.
    if ev.recommended:
        best = _best_on(top)
        why = f": best on {_join([_label(spec, m) for m in best])}" if best else ""
        out.append(Insight("recommendation",
                           f"{top.name} ranks first with a score of {top.score * 100:.0f}/100{why}.",
                           [top.id], best))
    else:
        broken = [c for c in top.constraints if not c.satisfied]
        detail = "; ".join(f"{c.description} (got {_fmt(spec, c.metric, c.value)})" for c in broken)
        out.append(Insight("constraint",
                           f"No future meets every constraint. The closest is {top.name}, which breaks: {detail}.",
                           [top.id], [c.metric for c in broken]))

    # 2. Trade-off between the top two feasible futures.
    feasible = [f for f in ev.futures if f.feasible]
    if len(feasible) >= 2:
        a, b = feasible[0], feasible[1]
        a_scores = {s.metric: s for s in a.objectives}
        worse = [s for s in b.objectives if s.value is not None and a_scores[s.metric].value is not None
                 and s.score > a_scores[s.metric].score]
        if worse:
            parts = ", ".join(f"{_label(spec, s.metric)} ({_fmt(spec, s.metric, a_scores[s.metric].value)} vs "
                              f"{_fmt(spec, s.metric, s.value)})" for s in worse)
            out.append(Insight("tradeoff",
                               f"Choosing {a.name} over {b.name} means accepting worse {parts}.",
                               [a.id, b.id], [s.metric for s in worse]))

    # 3. Dominated futures: never a good choice under these objectives (grouped by who beats them).
    groups: dict[str, list[FutureEvaluation]] = {}
    for f in ev.futures:
        if f.dominated_by:
            # Prefer a dominator that is itself on the Pareto front.
            front = [d for d in f.dominated_by if ev.by_id(d).pareto]
            groups.setdefault((front or f.dominated_by)[0], []).append(f)
    for by_id, losers in groups.items():
        listed = _join([f.name for f in losers])
        verb = "is" if len(losers) == 1 else "are"
        out.append(Insight("dominated",
                           f"{listed} {verb} dominated by {names[by_id]}: it is at least as good on every "
                           f"objective and better on at least one.", [f.id for f in losers] + [by_id]))

    # 4. Constraint violations.
    for f in ev.futures:
        for c in f.constraints:
            if not c.satisfied and f.id != (top.id if not ev.recommended else None):
                share = f" (holds in {c.satisfied_share:.0%} of runs)" if c.satisfied_share is not None else ""
                out.append(Insight("constraint",
                                   f"{f.name} breaks “{c.description}”: {_fmt(spec, c.metric, c.value)}{share}.",
                                   [f.id], [c.metric]))

    # 5. Robustness of the recommendation to the weights.
    if ev.robust is True:
        out.append(Insight("robustness",
                           f"The recommendation is robust: {names[ev.recommended]} stays first if any single "
                           f"weight is halved or doubled.", [ev.recommended]))
    elif ev.robust is False:
        flip = ev.weight_flips[0]
        verb = "doubling" if flip["factor"] > 1 else "halving"
        winner = names.get(flip["winner"], "no feasible future")
        out.append(Insight("robustness",
                           f"The recommendation depends on the weights: {verb} the weight of "
                           f"{_label(spec, flip['metric'])} would make {winner} the best choice.",
                           [ev.recommended] + ([flip["winner"]] if flip["winner"] else []), [flip["metric"]]))

    # 6. Opportunity: how much the recommendation improves on the baseline.
    if baseline_id and ev.recommended and baseline_id != ev.recommended and baseline_id in names:
        base = ev.by_id(baseline_id)
        rec = ev.by_id(ev.recommended)
        gains = []
        for s in rec.objectives:
            b = next(x for x in base.objectives if x.metric == s.metric)
            if s.value is not None and b.value is not None and s.score > b.score:
                gains.append(f"{_label(spec, s.metric)} {_fmt(spec, s.metric, b.value)} → "
                             f"{_fmt(spec, s.metric, s.value)}")
        if gains:
            out.append(Insight("opportunity", f"Compared with {base.name}, {rec.name} improves "
                                              f"{'; '.join(gains)}.", [base.id, rec.id]))

    # 7. Risk from Monte Carlo: tail risk and the main driver.
    for fid, mc in (montecarlo or {}).items():
        risk = mc.get("risk") or {}
        metric = risk.get("metric")
        if metric is None or risk.get("mean") is None or fid not in names:
            continue
        label = _label(spec, metric)
        if risk.get("p95") is not None and risk["p95"] > (risk["mean"] or 0) * 1.5 and risk["p95"] > 0:
            out.append(Insight("risk",
                               f"{names[fid]} has a heavy tail: mean {label} {_fmt(spec, metric, risk['mean'])}, "
                               f"but the worst 5% of runs average {_fmt(spec, metric, risk['worst_5_percent_mean'])}.",
                               [fid], [metric]))
        drivers = mc.get("drivers") or []
        if drivers and abs(drivers[0]["impact"]) > 0:
            d = drivers[0]
            out.append(Insight("risk",
                               f"In {names[fid]}, {d['event_id']} drives the most risk: mean {label} is "
                               f"{_fmt(spec, metric, d['mean_if_occurred'])} when it happens "
                               f"({d['frequency']:.0%} of runs) vs {_fmt(spec, metric, d['mean_if_not'])} when not.",
                               [fid], [metric]))
    return out
