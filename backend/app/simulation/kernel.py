"""The shared simulation kernel: time, the event queue, randomness and the causal log.

Every domain (infrastructure, hospital, cold chain) runs on this. A domain
model schedules items with ``at``/``after`` and receives them, one at a
time and in time order, in the handler it passes to ``run``. When something
important changes, the domain calls ``log(...)`` with the id of the log
entry that caused it, which is how "why did this happen?" works for every
domain without extra code.

Randomness
----------
``kernel.rng`` is ``random.Random(seed)``. It is used to decide whether
probabilistic scenario events happen (``sample_events``), exactly as the
original infrastructure engine did, so existing results are unchanged.

``kernel.stream(name)`` gives a separate, reproducible random stream per
purpose, e.g. "arrivals" or "demand". Using separate streams means that two
branches of a scenario see the *same* patient arrivals or the *same* demand
unless a decision changes them ("common random numbers"). Differences
between futures then come from the decisions, not from luck.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

from ..models import Event
from .event_queue import EventQueue, ScheduledEvent
from .state import LogEntry


class SimulationError(RuntimeError):
    pass


class Kernel:
    def __init__(self, until: float, seed: int = 0, max_steps: int = 100_000) -> None:
        if until <= 0:
            raise ValueError("until must be > 0")
        self.until = until
        self.seed = seed
        self.max_steps = max_steps
        self.now = 0.0
        self.queue = EventQueue()
        self.rng = random.Random(seed)
        self.log: list[LogEntry] = []
        self.steps = 0
        self._streams: dict[str, random.Random] = {}

    # ---- randomness ---------------------------------------------------
    def stream(self, name: str) -> random.Random:
        """An independent random stream for one purpose, fixed by (seed, name)."""
        if name not in self._streams:
            # Seeding with a string is deterministic across Python runs.
            self._streams[name] = random.Random(f"{self.seed}:{name}")
        return self._streams[name]

    def sample_events(self, events: list[Event]) -> tuple[list[Event], list[str]]:
        """Decide which events happen. Returns (occurring events, ids of skipped ones).

        Events are sorted by (start_time, id) first so the random numbers are
        drawn in the same order however the caller listed them.
        """
        occurring, skipped = [], []
        for event in sorted(events, key=lambda e: (e.start_time, e.id)):
            if event.probability < 1.0 and self.rng.random() >= event.probability:
                skipped.append(event.id)
            else:
                occurring.append(event)
        return occurring, skipped

    # ---- scheduling ---------------------------------------------------
    def at(self, time: float, kind: str, target: str, *, event_id: str | None = None,
           cause_id: int | None = None, data: dict[str, Any] | None = None,
           priority: int | None = None) -> None:
        """Schedule an item at an absolute time."""
        self.queue.push(ScheduledEvent(time, kind, target, event_id=event_id, cause_id=cause_id,
                                       data=data or {}, priority=priority))

    def after(self, delay: float, kind: str, target: str, **kwargs: Any) -> None:
        """Schedule an item ``delay`` time units from now."""
        self.at(self.now + delay, kind, target, **kwargs)

    # ---- causal log ---------------------------------------------------
    def log_entry(self, **kwargs: Any) -> LogEntry:
        """Record something that happened now. Pass ``cause_id`` to link it to its cause."""
        entry = LogEntry(id=len(self.log), time=self.now, **kwargs)
        self.log.append(entry)
        return entry

    # ---- main loop ----------------------------------------------------
    def run(self, handle: Callable[[ScheduledEvent], None]) -> None:
        """Pop items in time order and hand each to ``handle`` until ``until``."""
        while self.queue:
            item = self.queue.pop()
            if item.time > self.until:
                break
            self.steps += 1
            if self.steps > self.max_steps:
                raise SimulationError(
                    f"Exceeded {self.max_steps} steps; the system may be oscillating (check for cycles)."
                )
            self.now = item.time
            handle(item)
        self.now = self.until
