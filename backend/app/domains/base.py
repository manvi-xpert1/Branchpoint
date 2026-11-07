"""The contract between the shared engine and a domain.

The shared kernel (simulation/kernel.py) knows about time, the event
queue, randomness and the causal log. It does NOT know what a database, a
hospital ward or a warehouse is. Each domain supplies that knowledge as a
``Domain``:

* ``spec``: its catalog (entity, relationship, event and decision types,
  metrics with units and direction, assumptions), see ``spec.py``;
* ``simulate(...)``: run the model on the kernel and return an ``Outcome``;
* ``validate(...)``: domain-specific warnings about a system.

Domains whose model is "statuses spreading through dependencies" (software
infrastructure) implement the two ``DomainRules`` questions and reuse the
status-propagation ``Simulator``:

1. Given the events acting on a component, what is its own status?
2. Given its own status and the status of what it depends on, what is
   its effective status, and why?

Domains with queues, resources or stock (hospital, cold chain) write their
own model on the kernel instead.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..models import Component, Dependency, Event, Status, System
from ..simulation.state import Effect
from .spec import DomainSpec

if TYPE_CHECKING:  # imported only for type hints, avoiding an import cycle
    from ..simulation.outcome import Outcome


@dataclass
class Verdict:
    status: Status
    reason: str


class DomainRules(ABC):
    name: str = "base"

    @abstractmethod
    def intrinsic_status(self, component: Component, effects: list[Effect]) -> Verdict:
        """Status caused by events acting directly on the component."""

    @abstractmethod
    def effective_status(
        self,
        component: Component,
        intrinsic: Verdict,
        dependencies: list[tuple[Dependency, Status]],
    ) -> Verdict:
        """Final status, taking dependencies into account."""

    def validate(self, system: System) -> list[str]:
        """Domain-specific warnings. Empty list means no problems."""
        return []


class Domain(ABC):
    """One domain: its catalog, its model and its checks."""

    spec: DomainSpec

    @property
    def name(self) -> str:
        return self.spec.name

    @abstractmethod
    def simulate(self, system: System, events: list[Event], until: float, seed: int,
                 *, intervention_cost: float = 0.0) -> "Outcome":
        """Run one simulation of ``system`` with ``events`` and return its outcome."""

    def errors(self, system: System) -> list[str]:
        """Problems that make the system unusable in this domain (empty = fine)."""
        problems = []
        if not self.spec.open_entity_types:
            kinds = {e.type for e in self.spec.entity_types}
            for c in system.components.values():
                if c.type not in kinds:
                    problems.append(f"Component {c.id}: type {c.type!r} is not used in {self.spec.label}; "
                                    f"expected one of {sorted(kinds)}")
        allowed = self.spec.relationship_type_names
        for dep in system.dependencies:
            if dep.dependency_type not in allowed:
                problems.append(
                    f"Relationship {dep.id}: type {dep.dependency_type!r} is not used in "
                    f"{self.spec.label}; expected one of {sorted(allowed)}"
                )
        return problems

    def event_errors(self, events: list[Event]) -> list[str]:
        allowed = self.spec.event_type_names
        return [f"Event {e.id}: type {e.type!r} is not used in {self.spec.label}; "
                f"expected one of {sorted(allowed)}" for e in events if e.type not in allowed]

    def validate(self, system: System) -> list[str]:
        """Warnings that do not stop a simulation. Empty list means no problems."""
        return []
