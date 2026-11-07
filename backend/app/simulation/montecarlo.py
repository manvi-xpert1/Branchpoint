"""Monte Carlo: run one scenario many times and summarise the spread.

A single run answers "what happens with this seed?". When a scenario has
probabilistic events (probability < 1), different seeds give different
outcomes, so one run can be lucky or unlucky. Monte Carlo runs the same
scenario N times with seeds ``base_seed, base_seed + 1, ...`` and reports
the distribution: the average downtime, the typical (p50) and bad-case
(p95) downtime, the worst run, and how often each event happened.

Because seed i is always ``base_seed + i``, the whole batch is
reproducible: the same base seed gives exactly the same aggregates.

Besides the original downtime aggregates (kept for the infrastructure
UI), every batch now summarises **every metric** of the domain
(``metric_stats``), the domain's risk metric in more depth (``risk``:
mean, p95 and the average of the worst 5% of runs), and **risk drivers**:
for each probabilistic event, the mean risk in runs where it happened
versus runs where it did not.

This module is pure: no database, no web framework, no printing.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from ..domains.registry import get_domain
from ..models import System
from .branching import Scenario, run_scenario
from .outcome import MetricValues
from .stats import percentile  # noqa: F401  (re-exported: tests and callers import it from here)


@dataclass
class RunSample:
    """The outcome of one run in the batch."""

    seed: int
    metrics: MetricValues
    occurred: list[str]  # ids of events that happened in this run


@dataclass
class Aggregates:
    downtime_mean: float
    downtime_p50: float
    downtime_p95: float
    downtime_max: float
    p_any_downtime: float  # fraction of runs with downtime > 0
    availability_mean: float
    degraded_time_mean: float
    # event id -> fraction of runs in which it occurred
    event_frequency: dict[str, float]


@dataclass
class MetricStats:
    """Spread of one metric over the runs (runs where it was None are counted in ``missing``)."""

    mean: float | None
    std: float | None
    min: float | None
    p5: float | None
    p50: float | None
    p95: float | None
    max: float | None
    missing: int = 0


def metric_stats(values: list[float | None]) -> MetricStats:
    present = [float(v) for v in values if v is not None]
    missing = len(values) - len(present)
    if not present:
        return MetricStats(None, None, None, None, None, None, None, missing)
    mean = sum(present) / len(present)
    std = math.sqrt(sum((v - mean) ** 2 for v in present) / len(present))
    return MetricStats(
        mean=mean, std=std, min=min(present), p5=percentile(present, 5), p50=percentile(present, 50),
        p95=percentile(present, 95), max=max(present), missing=missing,
    )


def tail_mean(values: list[float], worst_share: float = 0.05, higher_is_worse: bool = True) -> float:
    """Average of the worst ``worst_share`` of values (CVaR / expected shortfall); at least one value."""
    ordered = sorted(values, reverse=higher_is_worse)
    k = max(1, math.ceil(len(ordered) * worst_share))
    return sum(ordered[:k]) / k


@dataclass
class RiskSummary:
    metric: str
    mean: float | None
    p95: float | None
    worst_5_percent_mean: float | None  # average of the worst 5% of runs
    p_nonzero: float | None  # share of runs with any risk (for lower-is-better metrics)


@dataclass
class Driver:
    """How much one probabilistic event moves the risk metric."""

    event_id: str
    frequency: float
    mean_if_occurred: float
    mean_if_not: float

    @property
    def impact(self) -> float:
        return self.mean_if_occurred - self.mean_if_not


@dataclass
class MonteCarloResult:
    scenario_id: str
    scenario_name: str
    runs: int
    base_seed: int
    until: float
    # True when every event has probability 1, so all runs are identical.
    deterministic: bool
    aggregates: Aggregates | None  # infrastructure-specific summary (None in other domains)
    samples: list[RunSample]
    domain: str = "software_infrastructure"
    event_ids: list[str] = field(default_factory=list)
    risk_metric: str = "downtime"
    metric_stats: dict[str, MetricStats] | None = None
    risk: RiskSummary | None = None
    drivers: list[Driver] | None = None

    def risk_values(self) -> list[float | None]:
        return [s.metrics.get(self.risk_metric) for s in self.samples]

    def to_dict(self) -> dict[str, Any]:
        """A compact, JSON-friendly summary.

        Keeps each run's downtime (one number per run, so the UI can draw
        a histogram) but not each run's full event log.
        """
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "runs": self.runs,
            "base_seed": self.base_seed,
            "until": self.until,
            "deterministic": self.deterministic,
            "aggregates": None if self.aggregates is None else asdict(self.aggregates),
            "downtimes": [s.metrics.get("downtime") for s in self.samples] if self.aggregates else [],
            "domain": self.domain,
            "risk_metric": self.risk_metric,
            "risk_values": self.risk_values(),
            "event_frequency": {eid: sum(1 for s in self.samples if eid in s.occurred) / self.runs
                                for eid in sorted({e for s in self.samples for e in s.occurred}
                                                  | set(self.event_ids))},
            "metric_stats": {k: asdict(v) for k, v in (self.metric_stats or {}).items()},
            "risk": None if self.risk is None else asdict(self.risk),
            "drivers": [{**asdict(d), "impact": d.impact} for d in (self.drivers or [])],
        }


def run_monte_carlo(
    system: System,
    scenario: Scenario,
    until: float,
    runs: int,
    base_seed: int | None = None,
) -> MonteCarloResult:
    """Run ``scenario`` ``runs`` times; run i uses seed ``base_seed + i``.

    ``base_seed`` defaults to the scenario's own seed, so run 0 of a
    Monte Carlo batch is the same as a normal single run.
    """
    if runs < 1:
        raise ValueError("runs must be at least 1")
    if base_seed is None:
        base_seed = scenario.seed

    events = scenario.resolved_events()
    event_ids = sorted(e.id for e in events)

    samples: list[RunSample] = []
    for i in range(runs):
        # replace() makes a shallow copy with a new seed, so the caller's
        # scenario is left untouched. run_scenario already deep-copies the system.
        seeded = replace(scenario, seed=base_seed + i)
        result = run_scenario(system, seeded, until)
        skipped = set(result.skipped_events)
        samples.append(RunSample(
            seed=seeded.seed,
            metrics=result.metrics,
            occurred=[eid for eid in event_ids if eid not in skipped],
        ))

    frequency = {eid: sum(1 for s in samples if eid in s.occurred) / runs for eid in event_ids}
    spec = get_domain(system.domain).spec
    aggregates = None
    if {"downtime", "availability", "degraded_time"} <= set(samples[0].metrics):
        downtimes = [s.metrics.downtime for s in samples]
        aggregates = Aggregates(
            downtime_mean=sum(downtimes) / runs,
            downtime_p50=percentile(downtimes, 50),
            downtime_p95=percentile(downtimes, 95),
            downtime_max=max(downtimes),
            p_any_downtime=sum(1 for d in downtimes if d > 0) / runs,
            availability_mean=sum(s.metrics.availability for s in samples) / runs,
            degraded_time_mean=sum(s.metrics.degraded_time for s in samples) / runs,
            event_frequency=frequency,
        )

    stats = {m.key: metric_stats([s.metrics.get(m.key) for s in samples]) for m in spec.metrics}
    risk_key = spec.risk_metric
    lower_is_better = spec.metric(risk_key).better != "higher"
    risk_values = [s.metrics.get(risk_key) for s in samples]
    present = [float(v) for v in risk_values if v is not None]
    risk = RiskSummary(
        metric=risk_key,
        mean=stats[risk_key].mean,
        p95=stats[risk_key].p95 if lower_is_better else stats[risk_key].p5,
        worst_5_percent_mean=tail_mean(present, 0.05, lower_is_better) if present else None,
        p_nonzero=(sum(1 for v in present if v > 0) / runs) if lower_is_better and present else None,
    )
    drivers = []
    for eid in event_ids:
        hit = [v for s, v in zip(samples, risk_values) if v is not None and eid in s.occurred]
        miss = [v for s, v in zip(samples, risk_values) if v is not None and eid not in s.occurred]
        if hit and miss:  # only events that sometimes happen and sometimes don't
            drivers.append(Driver(eid, frequency[eid], sum(hit) / len(hit), sum(miss) / len(miss)))
    drivers.sort(key=lambda d: abs(d.impact), reverse=True)

    return MonteCarloResult(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        runs=runs,
        base_seed=base_seed,
        until=until,
        deterministic=all(e.probability >= 1.0 for e in events),
        aggregates=aggregates,
        samples=samples,
        domain=spec.name,
        event_ids=event_ids,
        risk_metric=risk_key,
        metric_stats=stats,
        risk=risk,
        drivers=drivers,
    )
