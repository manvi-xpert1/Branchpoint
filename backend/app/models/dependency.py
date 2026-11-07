"""Dependencies: directed edges between components.

Direction convention (important!):
    source_id  DEPENDS ON  target_id

So ``Dependency("user_service", "postgres")`` means the user service relies
on Postgres. When the target breaks, the effect flows to the source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The infrastructure relationship types. Other domains add their own; the
# full list comes from the domain registry (see ``_check_type``).
DEPENDENCY_TYPES = {"requires", "optional", "fallback"}


def _check_type(dependency_id: str, dependency_type: str) -> None:
    # Imported here, not at the top, because the domains package imports models.
    from ..domains.registry import known_relationship_types

    known = known_relationship_types() | DEPENDENCY_TYPES
    if dependency_type not in known:
        raise ValueError(
            f"Dependency {dependency_id}: unknown type {dependency_type!r}; expected one of {sorted(known)}"
        )


@dataclass
class Dependency:
    id: str
    source_id: str
    target_id: str
    # requires: the source cannot work without the target (or its group).
    # optional: losing the target only degrades the source.
    # fallback: a backup that keeps the source running in degraded mode.
    dependency_type: str = "requires"
    # Dependencies sharing a group on the same source are interchangeable:
    # the source only needs ONE of them to be up (replicas, fallbacks).
    # No group means the dependency stands on its own.
    group: str | None = None
    # Simulated time units before a change in the target reaches the source.
    propagation_delay: float = 0.0
    # Domain-specific data, e.g. a routing probability, travel time or cost.
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _check_type(self.id, self.dependency_type)
        if self.propagation_delay < 0:
            raise ValueError(f"Dependency {self.id}: propagation_delay must be >= 0")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Dependency":
        return cls(
            id=data.get("id", f"{data['source_id']}->{data['target_id']}"),
            source_id=data["source_id"],
            target_id=data["target_id"],
            dependency_type=data.get("dependency_type", "requires"),
            group=data.get("group"),
            propagation_delay=float(data.get("propagation_delay", 0.0)),
            attributes=dict(data.get("attributes") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "dependency_type": self.dependency_type,
            "group": self.group,
            "propagation_delay": self.propagation_delay,
            "attributes": self.attributes,
        }
