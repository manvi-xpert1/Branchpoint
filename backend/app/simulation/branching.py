"""Scenarios, interventions and branch comparison.

A scenario never modifies the base system. To run one we:

1. Walk up to the root scenario and collect events and interventions,
   letting each child add to or override what its parent defined.
2. Deep-copy the base system and apply the interventions to the copy.
3. Run the simulator on that copy with the scenario's seed.

Branches are therefore fully independent and reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domains.registry import get_domain
from ..models import Component, Dependency, Event, System
from .engine import Simulator
from .metrics import Metrics, compute_metrics
from .state import LogEntry, SimulationState

INTERVENTION_TYPES = {
    "add_component",
    "remove_component",
    "add_dependency",
    "remove_dependency",
    "set_attribute",
}


@dataclass
class Intervention:
    """A change to the system made before the simulation starts."""

    id: str
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    cost: float = 0.0
    description: str = ""

    def __post_init__(self) -> None:
        if self.type not in INTERVENTION_TYPES:
            raise ValueError(f"Intervention {self.id}: unknown type {self.type!r}")

    def apply(self, system: System) -> None:
        p = self.params
        if self.type == "add_component":
            system.add_component(Component.from_dict(p))
        elif self.type == "remove_component":
            system.remove_component(p["id"])
        elif self.type == "add_dependency":
            system.add_dependency(Dependency.from_dict(p))
        elif self.type == "remove_dependency":
            system.remove_dependency(p["id"])
        elif self.type == "set_attribute":
            system.components[p["component_id"]].attributes[p["key"]] = p["value"]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Intervention":
        return cls(
            id=data["id"],
            type=data["type"],
            params=dict(data.get("params", {})),
            cost=float(data.get("cost", 0.0)),
            description=data.get("description", ""),
        )


@dataclass
class Scenario:
    id: str
    name: str
    events: list[Event] = field(default_factory=list)
    interventions: list[Intervention] = field(default_factory=list)
    parent: "Scenario | None" = None
    remove_event_ids: list[str] = field(default_factory=list)
    seed: int = 42

    def resolved_events(self) -> list[Event]:
        inherited = {e.id: e for e in self.parent.resolved_events()} if self.parent else {}
        for eid in self.remove_event_ids:
            inherited.pop(eid, None)
        for e in self.events:  # same id overrides the parent's event
            inherited[e.id] = e
        return list(inherited.values())

    def resolved_interventions(self) -> list[Intervention]:
        inherited = self.parent.resolved_interventions() if self.parent else []
        own_ids = {i.id for i in self.interventions}
        return [i for i in inherited if i.id not in own_ids] + list(self.interventions)

    def lineage(self) -> list[str]:
        return (self.parent.lineage() if self.parent else []) + [self.id]


@dataclass
class SimulationResult:
    scenario_id: str
    scenario_name: str
    seed: int
    metrics: Metrics
    state: SimulationState
    skipped_events: list[str]

    @property
    def log(self) -> list[LogEntry]:
        return self.state.log

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "seed": self.seed,
            "metrics": self.metrics.to_dict(),
            "skipped_events": self.skipped_events,
            "event_log": [e.to_dict() for e in self.log],
        }


def run_scenario(base_system: System, scenario: Scenario, until: float) -> SimulationResult:
    system = base_system.copy()
    interventions = scenario.resolved_interventions()
    for intervention in interventions:
        intervention.apply(system)

    sim = Simulator(system, get_domain(system.domain), until=until, seed=scenario.seed)
    sim.schedule(scenario.resolved_events())
    state = sim.run()
    cost = sum(i.cost for i in interventions)
    return SimulationResult(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        seed=scenario.seed,
        metrics=compute_metrics(state, until, cost),
        state=state,
        skipped_events=sim.skipped_events,
    )


def comparison_table(results: list[SimulationResult]) -> str:
    """Side-by-side metrics as a plain-text table."""
    headers = ["Scenario", "Availability", "Downtime", "Degraded", "Affected", "Recovery", "Cost"]
    rows = []
    for r in results:
        m = r.metrics
        rows.append([
            r.scenario_name,
            f"{m.availability:.1%}",
            f"{m.downtime:g}",
            f"{m.degraded_time:g}",
            str(m.affected_components),
            "-" if m.affected_components == 0
            else "not recovered" if m.recovery_time is None
            else f"{m.recovery_time:g}",
            f"{m.cost:g}",
        ])
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths))  # noqa: E731
    return "\n".join([line(headers), line(["-" * w for w in widths]), *map(line, rows)])
