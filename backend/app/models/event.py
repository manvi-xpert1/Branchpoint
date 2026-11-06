"""Events: things that happen to the system during a simulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

EVENT_TYPES = {"component_failure", "component_recovery", "traffic_spike", "latency_increase"}


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

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(
                f"Event {self.id}: unknown type {self.type!r}; expected one of {sorted(EVENT_TYPES)}"
            )
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
        }
