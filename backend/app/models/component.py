"""Components: the individual units of a simulated system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class Status(IntEnum):
    """Health of a component.

    An IntEnum, so statuses can be compared: a higher value is worse.
    ``max(a, b)`` returns the worse status and ``min(a, b)`` the better one.
    """

    HEALTHY = 0
    DEGRADED = 1
    FAILED = 2

    def __str__(self) -> str:  # nicer log output
        return self.name.lower()


@dataclass
class Component:
    id: str
    name: str
    type: str
    attributes: dict[str, Any] = field(default_factory=dict)
    # Entry points are what users see (e.g. API gateway). System
    # availability is measured at these components.
    entry_point: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Component":
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            type=data.get("type", "service"),
            attributes=dict(data.get("attributes", {})),
            entry_point=bool(data.get("entry_point", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "attributes": dict(self.attributes),
            "entry_point": self.entry_point,
        }
