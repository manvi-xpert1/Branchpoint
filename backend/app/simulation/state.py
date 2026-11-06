"""Mutable state of one simulation run. Every run gets its own copy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import Status, System


@dataclass
class Effect:
    """An active external event acting on a component."""

    event_id: str
    type: str
    severity: float


@dataclass
class LogEntry:
    id: int
    time: float
    kind: str  # "event" or "status_change"
    component_id: str
    message: str
    cause_id: int | None = None
    event_id: str | None = None
    old_status: Status | None = None
    new_status: Status | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "time": self.time,
            "kind": self.kind,
            "component_id": self.component_id,
            "message": self.message,
            "cause_id": self.cause_id,
            "event_id": self.event_id,
            "old_status": None if self.old_status is None else str(self.old_status),
            "new_status": None if self.new_status is None else str(self.new_status),
        }


@dataclass
class SimulationState:
    system: System
    time: float = 0.0
    status: dict[str, Status] = field(default_factory=dict)
    effects: dict[str, list[Effect]] = field(default_factory=dict)
    # component -> [(time, status)] each time its status changed
    timeline: dict[str, list[tuple[float, Status]]] = field(default_factory=dict)
    log: list[LogEntry] = field(default_factory=list)

    @classmethod
    def initial(cls, system: System) -> "SimulationState":
        state = cls(system=system)
        for cid in system.components:
            state.status[cid] = Status.HEALTHY
            state.effects[cid] = []
            state.timeline[cid] = [(0.0, Status.HEALTHY)]
        return state

    def add_log(self, **kwargs: Any) -> LogEntry:
        entry = LogEntry(id=len(self.log), time=self.time, **kwargs)
        self.log.append(entry)
        return entry

    def set_status(self, component_id: str, status: Status) -> None:
        self.status[component_id] = status
        self.timeline[component_id].append((self.time, status))
