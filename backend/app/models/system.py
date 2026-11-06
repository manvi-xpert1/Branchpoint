"""System: the full network of components and dependencies."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .component import Component
from .dependency import Dependency


class ValidationError(ValueError):
    """Raised when a system definition is invalid."""


@dataclass
class System:
    id: str
    name: str
    domain: str = "software_infrastructure"
    description: str = ""
    components: dict[str, Component] = field(default_factory=dict)
    dependencies: list[Dependency] = field(default_factory=list)

    # ---- construction -------------------------------------------------
    def add_component(self, component: Component) -> None:
        if component.id in self.components:
            raise ValidationError(f"Duplicate component id: {component.id}")
        self.components[component.id] = component

    def add_dependency(self, dependency: Dependency) -> None:
        self.dependencies.append(dependency)

    def remove_component(self, component_id: str) -> None:
        self.components.pop(component_id, None)
        self.dependencies = [
            d
            for d in self.dependencies
            if d.source_id != component_id and d.target_id != component_id
        ]

    def remove_dependency(self, dependency_id: str) -> None:
        self.dependencies = [d for d in self.dependencies if d.id != dependency_id]

    def copy(self) -> "System":
        """Deep copy, so a scenario can change a system without touching the original."""
        return copy.deepcopy(self)

    # ---- validation ---------------------------------------------------
    def validate(self) -> None:
        """Check structural problems early, with clear messages."""
        errors: list[str] = []
        seen_dep_ids: set[str] = set()
        for dep in self.dependencies:
            if dep.id in seen_dep_ids:
                errors.append(f"Duplicate dependency id: {dep.id}")
            seen_dep_ids.add(dep.id)
            if dep.source_id not in self.components:
                errors.append(f"Dependency {dep.id}: unknown source {dep.source_id!r}")
            if dep.target_id not in self.components:
                errors.append(f"Dependency {dep.id}: unknown target {dep.target_id!r}")
            if dep.source_id == dep.target_id:
                errors.append(f"Dependency {dep.id}: component cannot depend on itself")
        if errors:
            raise ValidationError("Invalid system:\n  " + "\n  ".join(errors))

    # ---- serialisation ------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "System":
        system = cls(
            id=data.get("id", "system"),
            name=data.get("name", data.get("id", "system")),
            domain=data.get("domain", "software_infrastructure"),
            description=data.get("description", ""),
        )
        for c in data.get("components", []):
            system.add_component(Component.from_dict(c))
        for d in data.get("dependencies", []):
            system.add_dependency(Dependency.from_dict(d))
        system.validate()
        return system

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "domain": self.domain,
            "description": self.description,
            "components": [c.to_dict() for c in self.components.values()],
            "dependencies": [d.to_dict() for d in self.dependencies],
        }
