"""Status propagation on top of the shared kernel (software infrastructure).

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

from ..domains.base import DomainRules
from ..models import Event, Status, System
from .event_queue import END, EVALUATE, START, ScheduledEvent
from .graph import DependencyGraph
from .kernel import Kernel, SimulationError
from .state import Effect, LogEntry, SimulationState

__all__ = ["Simulator", "SimulationError", "explain", "first_change"]


class Simulator:
    """Status propagation through a dependency graph, running on the shared Kernel.

    Used by the software-infrastructure domain. The kernel owns time, the
    queue, randomness and the log; this class owns what START/END/EVALUATE
    mean: effects on components and statuses spreading to dependents.
    """

    def __init__(
        self,
        system: System,
        rules: DomainRules,
        until: float,
        seed: int = 0,
        max_steps: int = 100_000,
    ) -> None:
        system.validate()
        self.kernel = Kernel(until, seed, max_steps)
        self.system = system
        self.rules = rules
        self.until = until
        self.max_steps = max_steps
        self.graph = DependencyGraph(system)
        self.state = SimulationState.initial(system)
        self.state.log = self.kernel.log  # one log, owned by the kernel
        self.skipped_events: list[str] = []  # probabilistic events that did not occur
        # Load flow is opt-in: only dependencies with a load_share forward load.
        self.load_edges = [d for d in system.dependencies if _number(d.attributes.get("load_share")) is not None]
        self._load_order = self._order_for_load() if self.load_edges else []

    @property
    def rng(self):
        return self.kernel.rng

    @property
    def queue(self):
        return self.kernel.queue

    # ---- scheduling ---------------------------------------------------
    def schedule(self, events: list[Event]) -> None:
        for event in events:
            if event.target_id not in self.system.components:
                raise SimulationError(f"Event {event.id}: unknown target {event.target_id!r}")
        occurring, skipped = self.kernel.sample_events(events)
        self.skipped_events.extend(skipped)
        for event in occurring:
            data = {"type": event.type, "severity": event.severity}
            self.kernel.at(event.start_time, START, event.target_id, event_id=event.id, data=data)

            duration = event.duration
            if duration is None and event.type == "component_failure":
                duration = self.system.components[event.target_id].attributes.get("recovery_time")
            if duration is not None and event.type != "component_recovery":
                self.kernel.at(event.start_time + duration, END, event.target_id, event_id=event.id, data=data)

    # ---- main loop ----------------------------------------------------
    def run(self) -> SimulationState:
        self.kernel.run(self._handle)
        self.state.time = self.until
        return self.state

    def _handle(self, item: ScheduledEvent) -> None:
        self.state.time = self.kernel.now
        if item.kind == START:
            self._start(item)
        elif item.kind == END:
            self._end(item)
        else:
            self._evaluate(item.component_id, item.cause_id)

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
        entry = self.kernel.log_entry(
            kind="event", component_id=item.component_id, message=msg, event_id=item.event_id
        )
        self._after_effect_change(item.component_id, entry.id)

    def _end(self, item: ScheduledEvent) -> None:
        effects = self.state.effects[item.component_id]
        before = len(effects)
        effects[:] = [e for e in effects if e.event_id != item.event_id]
        if len(effects) == before:
            return  # already cleared (e.g. by an explicit recovery event)
        entry = self.kernel.log_entry(
            kind="event",
            component_id=item.component_id,
            message=f"{item.data['type'].replace('_', ' ')} ends",
            event_id=item.event_id,
        )
        self._after_effect_change(item.component_id, entry.id)

    def _after_effect_change(self, component_id: str, cause_id: int) -> None:
        self._record_load(component_id)
        self._evaluate(component_id, cause_id)
        if self.load_edges:
            self._propagate_load(cause_id)

    # ---- load flow (opt-in) --------------------------------------------
    def _order_for_load(self) -> list[str]:
        """Callers before the things they call, so extra load can be pushed downstream."""
        try:
            return list(reversed(self.graph.topological_order()))
        except ValueError:  # cycles: one pass in definition order (documented limitation)
            return list(self.system.components)

    def _propagate_load(self, cause_id: int) -> None:
        """Recompute the load each component receives from its callers.

        A caller's extra load (its load minus its normal ``current_load``)
        is forwarded to each target in proportion to the dependency's
        ``load_share``. Targets whose inherited load changed are logged
        (linked to the cause) and re-evaluated.
        """
        load_of = getattr(self.rules, "load_of")
        inherited = {cid: 0.0 for cid in self.system.components}
        by_source: dict[str, list] = {}
        for d in self.load_edges:
            by_source.setdefault(d.source_id, []).append(d)
        for cid in self._load_order:
            component = self.system.components[cid]
            own = [e for e in self.state.effects[cid] if e.type != "inherited_load"]
            total = load_of(component, own) + inherited[cid]
            extra = total - float(component.attributes.get("current_load", 0) or 0)
            for d in by_source.get(cid, []):
                inherited[d.target_id] += extra * float(d.attributes["load_share"])
        for cid, amount in inherited.items():
            effects = self.state.effects[cid]
            current = sum(e.severity for e in effects if e.type == "inherited_load")
            if abs(current - amount) < 1e-9:
                continue
            effects[:] = [e for e in effects if e.type != "inherited_load"]
            if abs(amount) > 1e-9:
                effects.append(Effect("load-flow", "inherited_load", amount))
            entry = self.kernel.log_entry(
                kind="event", component_id=cid, cause_id=cause_id,
                message=f"load from callers {'+' if amount >= 0 else ''}{amount:g} (was {current:+g})",
            )
            self._record_load(cid)
            self._evaluate(cid, entry.id)

    def _record_load(self, component_id: str) -> None:
        timeline = self.state.load.get(component_id)
        load_of = getattr(self.rules, "load_of", None)
        if timeline is None or load_of is None:
            return
        load = load_of(self.system.components[component_id], self.state.effects[component_id])
        if load != timeline[-1][1]:
            if timeline[-1][0] == self.kernel.now:
                timeline[-1] = (self.kernel.now, load)
            else:
                timeline.append((self.kernel.now, load))

    def _evaluate(self, component_id: str, cause_id: int | None) -> None:
        component = self.system.components[component_id]
        intrinsic = self.rules.intrinsic_status(component, self.state.effects[component_id])
        own = self.state.intrinsic[component_id]
        if own[-1][1] != intrinsic.status:
            own.append((self.kernel.now, intrinsic.status))
        deps = [(d, self.state.status[d.target_id]) for d in self.graph.depends_on[component_id]]
        verdict = self.rules.effective_status(component, intrinsic, deps)

        old = self.state.status[component_id]
        if verdict.status == old:
            return
        self.state.set_status(component_id, verdict.status)
        entry = self.kernel.log_entry(
            kind="status_change",
            component_id=component_id,
            message=f"{old} -> {verdict.status}: {verdict.reason}",
            cause_id=cause_id,
            old_status=old,
            new_status=verdict.status,
        )
        for dep in self.graph.dependents[component_id]:
            self.kernel.after(dep.propagation_delay, EVALUATE, dep.source_id, cause_id=entry.id)


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


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
