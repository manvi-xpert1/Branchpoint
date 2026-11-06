"""The contract between the shared engine and a domain.

The engine knows about events, time, effects and graphs. It does NOT know
what a database or a warehouse is. A domain supplies that knowledge by
answering two questions:

1. Given the events acting on a component, what is its own status?
2. Given its own status and the status of what it depends on, what is
   its effective status, and why?

A future supply-chain domain implements the same two methods.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import Component, Dependency, Status, System
from ..simulation.state import Effect


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
