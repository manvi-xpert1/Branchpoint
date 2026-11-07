"""Events: things that happen to the system during a simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The infrastructure event types. Other domains add their own; the full
# list comes from the domain registry (see ``_check_type``).
EVENT_TYPES = {"component_failure", "component_recovery", "traffic_spike", "latency_increase"}


def _check_type(event_id: str, event_type: str) -> None:
    # Imported here, not at the top, because the domains package imports models.
    from ..domains.registry import known_event_types

    known = known_event_types() | EVENT_TYPES
    if event_type not in known:
        raise ValueError(f"Event {event_id}: unknown type {event_type!r}; expected one of {sorted(known)}")


@dataclass
class Event:
    id: str
    type: str
    target_id: str
    start_time: float
    # How long the effect lasts. None means "until something else changes
    # it" (for failures, the component's ``recovery_time`` attribute is
    # used if it has one).
    duration: float | None = None
    # Meaning depends on the type. For traffic_spike it is the load
    # multiplier (2.0 = double traffic). Otherwise it is unused for now.
    severity: float = 1.0
    # < 1.0 makes the event probabilistic: each run samples whether it
    # happens, using the scenario's random seed.
    probability: float = 1.0
    # Domain-specific settings (e.g. how many staff are unavailable).
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _check_type(self.id, self.type)
        if self.start_time < 0:
            raise ValueError(f"Event {self.id}: start_time must be >= 0")
        if self.duration is not None and self.duration <= 0:
            raise ValueError(f"Event {self.id}: duration must be > 0")
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(f"Event {self.id}: probability must be between 0 and 1")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        duration = data.get("duration")
        return cls(
            id=data["id"],
            type=data["type"],
            target_id=data["target_id"],
            start_time=float(data.get("start_time", 0.0)),
            duration=None if duration is None else float(duration),
            severity=float(data.get("severity", 1.0)),
            probability=float(data.get("probability", 1.0)),
            params=dict(data.get("params") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "target_id": self.target_id,
            "start_time": self.start_time,
            "duration": self.duration,
            "severity": self.severity,
            "probability": self.probability,
            "params": self.params,
        }
