"""A priority queue of scheduled simulation events, built on heapq."""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from typing import Any

# Kinds of internal events the engine processes.
START = "start"  # an external event begins (failure, spike, ...)
END = "end"  # an external event's duration is over
EVALUATE = "evaluate"  # re-check a component's status after a dependency changed

# At equal times, apply external changes before re-evaluating components,
# so an evaluation sees everything that happened at that instant.
# Domains may use their own kinds; those default to the START priority
# unless the item sets ``priority`` itself.
_PRIORITY = {END: 0, START: 1, EVALUATE: 2}
DEFAULT_PRIORITY = 1


@dataclass
class ScheduledEvent:
    time: float
    kind: str
    component_id: str
    event_id: str | None = None  # the external Event this belongs to
    cause_id: int | None = None  # log entry that triggered this (for explanations)
    data: dict[str, Any] = field(default_factory=dict)
    priority: int | None = None  # overrides the priority of ``kind``


class EventQueue:
    """Pops events in (time, priority, insertion order).

    The insertion counter makes ordering fully deterministic: two events
    at the same time and priority come out in the order they were added.
    That is what makes runs reproducible.
    """

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, int, ScheduledEvent]] = []
        self._counter = itertools.count()

    def push(self, event: ScheduledEvent) -> None:
        priority = event.priority if event.priority is not None else _PRIORITY.get(event.kind, DEFAULT_PRIORITY)
        heapq.heappush(self._heap, (event.time, priority, next(self._counter), event))

    def pop(self) -> ScheduledEvent:
        return heapq.heappop(self._heap)[-1]

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)
