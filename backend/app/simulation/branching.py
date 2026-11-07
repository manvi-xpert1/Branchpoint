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
from .outcome import MetricValues, Outcome
from .state import LogEntry

INTERVENTION_TYPES = {
    "add_component",
    "remove_component",
    "add_dependency",
    "remove_dependency",
    "set_attribute",
    "set_dependency_attribute",
    "set_parameter",
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
        elif self.type == "set_dependency_attribute":
            dep = next((d for d in system.dependencies if d.id == p["dependency_id"]), None)
            if dep is None:
                raise KeyError(f"no dependency {p['dependency_id']!r}")
            dep.attributes[p["key"]] = p["value"]
        elif self.type == "set_parameter":
            system.parameters[p["key"]] = p["value"]

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
    domain: str
    outcome: Outcome

    @property
    def metrics(self) -> MetricValues:
        return self.outcome.metrics

    @property
    def log(self) -> list[LogEntry]:
        return self.outcome.log

    @property
    def timelines(self):
        return self.outcome.timelines

    @property
    def series(self):
        return self.outcome.series

    @property
    def skipped_events(self) -> list[str]:
        return self.outcome.skipped_events

    @property
    def state(self):
        """The domain's own final state (for infrastructure: SimulationState)."""
        return self.outcome.state

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
    """Run one scenario: apply its decisions to a copy of the system, then simulate."""
    system = base_system.copy()
    interventions = scenario.resolved_interventions()
    for intervention in interventions:
        intervention.apply(system)

    domain = get_domain(system.domain)
    events = scenario.resolved_events()
    problems = domain.errors(system) + domain.event_errors(events)
    if problems:
        raise ValueError("; ".join(problems))
    outcome = domain.simulate(system, events, until, scenario.seed,
                              intervention_cost=sum(i.cost for i in interventions))
    return SimulationResult(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        seed=scenario.seed,
        domain=domain.name,
        outcome=outcome,
    )


def comparison_table(results: list[SimulationResult]) -> str:
    """Side-by-side metrics as a plain-text table, with the columns of the results' domain."""
    from ..domains.spec import format_value

    spec = get_domain(results[0].domain).spec
    # Skip opt-in metrics no result has a value for (e.g. latency on a system without latencies).
    metrics = [m for m in spec.metrics if any(r.metrics.get(m.key) is not None for r in results)
               or m.key == "recovery_time"]
    headers = ["Scenario", *(m.label for m in metrics)]
    rows = [[r.scenario_name, *(format_value(m, r.metrics.get(m.key)) for m in metrics)] for r in results]
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths))  # noqa: E731
    return "\n".join([line(headers), line(["-" * w for w in widths]), *map(line, rows)])
