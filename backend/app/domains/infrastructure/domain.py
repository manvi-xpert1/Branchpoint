"""The software-infrastructure domain: status propagation on the shared kernel."""

from __future__ import annotations

from dataclasses import asdict

from ...models import Event, System
from ...simulation.engine import Simulator
from ...simulation.metrics import compute_metrics, entry_latency_series
from ...simulation.outcome import MetricValues, Outcome
from ..base import Domain
from .rules import InfrastructureRules
from .spec import INFRASTRUCTURE_SPEC


class InfrastructureDomain(Domain):
    spec = INFRASTRUCTURE_SPEC

    def __init__(self) -> None:
        self.rules = InfrastructureRules()

    def simulate(self, system: System, events: list[Event], until: float, seed: int,
                 *, intervention_cost: float = 0.0) -> Outcome:
        sim = Simulator(system, self.rules, until=until, seed=seed)
        sim.schedule(events)
        state = sim.run()
        metrics = compute_metrics(state, until, intervention_cost)
        series: dict[str, dict[str, list[list]]] = {}
        if any(len(tl) > 1 for tl in state.load.values()):
            series["load"] = {cid: [[t, v] for t, v in tl] for cid, tl in state.load.items()}
        latency = entry_latency_series(state, until)
        if latency is not None:
            series["latency"] = {"entry points": [[t, v] for t, v in latency]}
        return Outcome(
            metrics=MetricValues(asdict(metrics)),
            log=state.log,
            timelines=state.timeline,
            series=series,
            skipped_events=sim.skipped_events,
            state=state,
        )

    def validate(self, system: System) -> list[str]:
        return self.rules.validate(system)
