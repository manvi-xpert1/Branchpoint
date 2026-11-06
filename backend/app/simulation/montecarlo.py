"""Monte Carlo: run one scenario many times and summarise the spread.

A single run answers "what happens with this seed?". When a scenario has
probabilistic events (probability < 1), different seeds give different
outcomes, so one run can be lucky or unlucky. Monte Carlo runs the same
scenario N times with seeds ``base_seed, base_seed + 1, ...`` and reports
the distribution: the average downtime, the typical (p50) and bad-case
(p95) downtime, the worst run, and how often each event happened.

Because seed i is always ``base_seed + i``, the whole batch is
reproducible: the same base seed gives exactly the same aggregates.

This module is pure: no database, no web framework, no printing.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Any

from ..models import System
from .branching import Scenario, run_scenario
from .metrics import Metrics


def percentile(values: list[float], q: float) -> float:
    """The q-th percentile (0-100) using linear interpolation.

    Sort the values and imagine them at positions 0..n-1. The q-th
    percentile sits at position (n - 1) * q / 100; if that falls between
    two values we interpolate. This matches numpy's default method.
    """
    if not values:
        raise ValueError("percentile of an empty list")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100
    lower, upper = math.floor(pos), math.ceil(pos)
    if lower == upper:
        return float(ordered[lower])
    fraction = pos - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


@dataclass
class RunSample:
    """The outcome of one run in the batch."""

    seed: int
    metrics: Metrics
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
class MonteCarloResult:
    scenario_id: str
    scenario_name: str
    runs: int
    base_seed: int
    until: float
    # True when every event has probability 1, so all runs are identical.
    deterministic: bool
    aggregates: Aggregates
    samples: list[RunSample]

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
            "aggregates": asdict(self.aggregates),
            "downtimes": [s.metrics.downtime for s in self.samples],
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

    downtimes = [s.metrics.downtime for s in samples]
    aggregates = Aggregates(
        downtime_mean=sum(downtimes) / runs,
        downtime_p50=percentile(downtimes, 50),
        downtime_p95=percentile(downtimes, 95),
        downtime_max=max(downtimes),
        p_any_downtime=sum(1 for d in downtimes if d > 0) / runs,
        availability_mean=sum(s.metrics.availability for s in samples) / runs,
        degraded_time_mean=sum(s.metrics.degraded_time for s in samples) / runs,
        event_frequency={
            eid: sum(1 for s in samples if eid in s.occurred) / runs for eid in event_ids
        },
    )
    return MonteCarloResult(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        runs=runs,
        base_seed=base_seed,
        until=until,
        deterministic=all(e.probability >= 1.0 for e in events),
        aggregates=aggregates,
        samples=samples,
    )
