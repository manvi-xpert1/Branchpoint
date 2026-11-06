"""The discrete-event simulation loop. Domain-independent.

Overview of one run:

1. Each external Event becomes a START (and, if it has a duration, an END)
   in a priority queue. Probabilistic events are sampled with a seeded RNG.
2. Pop the earliest item. START/END add or remove an effect on a
   component and then re-evaluate it.
3. Re-evaluating asks the domain rules for the component's status. If it
   changed, the change is logged with its cause, and every dependent is
   scheduled for re-evaluation after the dependency's propagation delay.
4. Repeat until the queue is empty or the end time is reached.

Every status change points to the log entry that caused it, so any impact
can be traced back to the original event (see ``explain``).

Note on delays: a delayed evaluation reads the dependency's status *when
it runs*, not when the change happened. A blip shorter than the delay
can therefore be absorbed without reaching dependents.
"""

from __future__ import annotations

import random

from ..domains.base import DomainRules
from ..models import Event, Status, System
from .event_queue import END, EVALUATE, START, EventQueue, ScheduledEvent
from .graph import DependencyGraph
from .state import Effect, LogEntry, SimulationState


class SimulationError(RuntimeError):
    pass


class Simulator:
    def __init__(
        self,
        system: System,
        rules: DomainRules,
        until: float,
        seed: int = 0,
        max_steps: int = 100_000,
    ) -> None:
        system.validate()
        if until <= 0:
            raise ValueError("until must be > 0")
        self.system = system
        self.rules = rules
        self.until = until
        self.rng = random.Random(seed)
        self.max_steps = max_steps
        self.graph = DependencyGraph(system)
        self.state = SimulationState.initial(system)
        self.queue = EventQueue()
        self.skipped_events: list[str] = []  # probabilistic events that did not occur

    # ---- scheduling ---------------------------------------------------
    def schedule(self, events: list[Event]) -> None:
        # Sort by id first so the RNG is consumed in the same order
        # regardless of how the caller ordered the list.
        for event in sorted(events, key=lambda e: (e.start_time, e.id)):
            if event.target_id not in self.system.components:
                raise SimulationError(f"Event {event.id}: unknown target {event.target_id!r}")
            if event.probability < 1.0 and self.rng.random() >= event.probability:
                self.skipped_events.append(event.id)
                continue
            data = {"type": event.type, "severity": event.severity}
            self.queue.push(ScheduledEvent(event.start_time, START, event.target_id, event.id, data=data))

            duration = event.duration
            if duration is None and event.type == "component_failure":
                duration = self.system.components[event.target_id].attributes.get("recovery_time")
            if duration is not None and event.type != "component_recovery":
                self.queue.push(
                    ScheduledEvent(event.start_time + duration, END, event.target_id, event.id, data=data)
                )

    # ---- main loop ----------------------------------------------------
    def run(self) -> SimulationState:
        steps = 0
        while self.queue:
            item = self.queue.pop()
            if item.time > self.until:
                break
            steps += 1
            if steps > self.max_steps:
                raise SimulationError(
                    f"Exceeded {self.max_steps} steps; the system may be oscillating (check for cycles)."
                )
            self.state.time = item.time
            if item.kind == START:
                self._start(item)
            elif item.kind == END:
                self._end(item)
            else:
                self._evaluate(item.component_id, item.cause_id)
        self.state.time = self.until
        return self.state

    # ---- handlers -----------------------------------------------------
    def _start(self, item: ScheduledEvent) -> None:
        effects = self.state.effects[item.component_id]
        etype = item.data["type"]
        if etype == "component_recovery":
            # Recovery clears any active failure on the component.
            effects[:] = [e for e in effects if e.type != "component_failure"]
            msg = "recovery applied"
        else:
            effects.append(Effect(item.event_id or "", etype, item.data["severity"]))
            msg = f"{etype.replace('_', ' ')} begins"
        entry = self.state.add_log(
            kind="event", component_id=item.component_id, message=msg, event_id=item.event_id
        )
        self._evaluate(item.component_id, entry.id)

    def _end(self, item: ScheduledEvent) -> None:
        effects = self.state.effects[item.component_id]
        before = len(effects)
        effects[:] = [e for e in effects if e.event_id != item.event_id]
        if len(effects) == before:
            return  # already cleared (e.g. by an explicit recovery event)
        entry = self.state.add_log(
            kind="event",
            component_id=item.component_id,
            message=f"{item.data['type'].replace('_', ' ')} ends",
            event_id=item.event_id,
        )
        self._evaluate(item.component_id, entry.id)

    def _evaluate(self, component_id: str, cause_id: int | None) -> None:
        component = self.system.components[component_id]
        intrinsic = self.rules.intrinsic_status(component, self.state.effects[component_id])
        deps = [(d, self.state.status[d.target_id]) for d in self.graph.depends_on[component_id]]
        verdict = self.rules.effective_status(component, intrinsic, deps)

        old = self.state.status[component_id]
        if verdict.status == old:
            return
        self.state.set_status(component_id, verdict.status)
        entry = self.state.add_log(
            kind="status_change",
            component_id=component_id,
            message=f"{old} -> {verdict.status}: {verdict.reason}",
            cause_id=cause_id,
            old_status=old,
            new_status=verdict.status,
        )
        for dep in self.graph.dependents[component_id]:
            self.queue.push(
                ScheduledEvent(
                    self.state.time + dep.propagation_delay, EVALUATE, dep.source_id, cause_id=entry.id
                )
            )


def explain(log: list[LogEntry], entry_id: int) -> list[LogEntry]:
    """Follow cause links from a log entry back to the original event."""
    chain = []
    current: int | None = entry_id
    while current is not None:
        entry = log[current]
        chain.append(entry)
        current = entry.cause_id
    return list(reversed(chain))


def first_change(log: list[LogEntry], component_id: str, status: Status) -> LogEntry | None:
    for entry in log:
        if entry.kind == "status_change" and entry.component_id == component_id and entry.new_status == status:
            return entry
    return None
