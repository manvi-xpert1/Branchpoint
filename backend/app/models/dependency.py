"""Dependencies: directed edges between components.

Direction convention (important!):
    source_id  DEPENDS ON  target_id

So ``Dependency("user_service", "postgres")`` means the user service relies
on Postgres. When the target breaks, the effect flows to the source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEPENDENCY_TYPES = {"requires", "optional", "fallback"}


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

    def __post_init__(self) -> None:
        if self.dependency_type not in DEPENDENCY_TYPES:
            raise ValueError(
                f"Dependency {self.id}: unknown type {self.dependency_type!r}; "
                f"expected one of {sorted(DEPENDENCY_TYPES)}"
            )
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
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "dependency_type": self.dependency_type,
            "group": self.group,
            "propagation_delay": self.propagation_delay,
        }
