"""Hospital patient flow: a discrete-event queueing model on the shared kernel.

How one run works
-----------------
* **Arrivals.** Each ``arrivals`` node generates patients at random times
  (a Poisson process: gaps between patients are exponential with mean
  1 / rate). An ``arrival_surge`` multiplies the rate while it lasts.
* **Routing.** A patient leaving a node picks the next unit using the
  ``probability`` on its ``routes_to`` relationships. If the shares add up
  to less than 1, the remaining share is discharged.
* **Units.** A unit has ``capacity`` beds/staff and a mean ``service_time``.
  If a bed is free and nobody is waiting, treatment starts at once;
  otherwise the patient joins a first-come-first-served queue.
* **Boarding (blocking).** When a patient is ready to move on but the next
  unit is full, and the current unit has ``hold_bed_while_waiting``, the
  patient keeps their current bed until the next unit takes them. This is
  how a full ward makes the emergency department crowded.
* **Leaving before treatment.** With ``max_wait`` set, a patient still in a
  unit's queue after that long leaves (unless they are holding a bed
  elsewhere, i.e. boarding).
* **Disruptions.** ``staff_shortage`` removes beds/staff, ``unit_closure``
  removes all of them, ``service_slowdown`` multiplies treatment times.
  Patients already being treated finish; the change affects new starts.

Randomness: every patient gets their own random stream, seeded from the
run seed and the patient's number. A patient therefore arrives at the same
time, takes the same path and needs the same treatment time in every
branch (common random numbers), so differences between futures come from
the decisions, not from luck.

Statuses (for the graph and the causal log): a unit is DEGRADED (crowded)
when its queue reaches ``crowding_queue`` (default: its capacity, at least 5) and
FAILED when the queue reaches three times that, or when it has no
available beds while patients wait. To avoid flicker it returns to the
better status only when the queue has fallen to half of the threshold.
Each status change links to the most likely cause: a disruption on the
unit, a crowded unit downstream that it is boarding patients for, or an
arrival surge. With none of those it is marked as normal variation.

Everything here is an operational planning model with illustrative
numbers. It makes no clinical claims.
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field

from ...models import Event, Status, System
from ...simulation.kernel import Kernel
from ...simulation.metrics import time_in_status, worst_of
from ...simulation.stats import percentile
from ...simulation.outcome import MetricValues, Outcome
from ..base import Domain
from .spec import HOSPITAL_SPEC

UNIT_TYPES = {"triage", "emergency", "diagnostics", "ward", "icu"}
MAX_PATIENTS = 200_000  # per run; protects the server from accidental huge inputs

# Queue priorities at the same moment: event ends, then starts, then patient moves, then samples.
P_END, P_START, P_FLOW, P_SAMPLE = 0, 1, 2, 9


def _num(value, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


@dataclass
class Patient:
    id: int
    arrived: float
    rng: random.Random
    wait: float = 0.0  # total time in queues so far
    waiting_since: float | None = None
    boarding: float = 0.0
    boarding_since: float | None = None
    done: bool = False
    preexisting: bool = False  # already in a bed at t=0; left out of arrival and wait figures


@dataclass
class QueueEntry:
    patient: Patient
    since: float
    holding: str | None  # unit whose bed the patient keeps while waiting (boarding)
    active: bool = True


@dataclass
class Unit:
    id: str
    capacity: int
    service_time: float
    max_wait: float | None
    crowd: int
    hold: bool
    cost_per_hour: float | None
    unavailable: float = 0.0  # beds/staff removed by shortages
    closed: int = 0  # active closures
    slowdown: float = 1.0
    busy: int = 0
    queue: deque = field(default_factory=deque)
    queued: int = 0  # active entries in the queue
    busy_area: float = 0.0  # integral of busy over time, for utilisation
    last_change: float = 0.0
    peak_queue: int = 0
    causes: list[int] = field(default_factory=list)  # log ids of active disruptions here

    @property
    def available(self) -> int:
        return 0 if self.closed else max(0, int(math.floor(self.capacity - self.unavailable)))


class HospitalModel:
    def __init__(self, system: System, events: list[Event], until: float, seed: int) -> None:
        self.system = system
        self.until = until
        self.seed = seed
        self.kernel = Kernel(until, seed, max_steps=5_000_000)
        self.units: dict[str, Unit] = {}
        self.sources: dict[str, dict] = {}
        self.routes: dict[str, list[tuple[str, float]]] = {}
        self.patients: list[Patient] = []
        self.left = 0
        self.discharged_los: list[float] = []
        self.status: dict[str, Status] = {}
        self.timeline: dict[str, list[tuple[float, Status]]] = {}
        self.status_entry: dict[str, int] = {}  # unit -> log id of its last status change
        self.surge_causes: list[int] = []
        self.series = {"queue": {}, "in_use": {}}
        self._build()
        occurring, self.skipped = self.kernel.sample_events(events)
        for e in occurring:
            data = {"type": e.type, "severity": e.severity}
            self.kernel.at(e.start_time, "start", e.target_id, event_id=e.id, data=data, priority=P_START)
            if e.duration is not None:
                self.kernel.at(e.start_time + e.duration, "end", e.target_id, event_id=e.id, data=data,
                               priority=P_END)
        for sid in self.sources:
            self._schedule_arrival(sid)
        self.initial: list[Patient] = []
        for c in system.components.values():
            unit = self.units.get(c.id)
            n = int(_num(c.attributes.get("occupied_at_start"), 0)) if unit else 0
            for k in range(min(n, unit.capacity) if unit else 0):
                p = Patient(-1, 0.0, random.Random(f"{seed}:start:{c.id}:{k}"), preexisting=True)
                self.initial.append(p)
                self._start(p, unit, None)
        step = until / 120
        for i in range(121):
            self.kernel.at(min(until, i * step), "sample", "", priority=P_SAMPLE)

    # ---- set-up -------------------------------------------------------------
    def _build(self) -> None:
        for c in self.system.components.values():
            a = c.attributes
            if c.type == "arrivals":
                self.sources[c.id] = {"rate": _num(a.get("rate"), 0.0), "multiplier": 1.0, "version": 0,
                                      "count": 0}
            else:
                capacity = int(_num(a.get("capacity"), 1))
                crowd = int(_num(a.get("crowding_queue"), 0)) or max(5, capacity)
                max_wait = _num(a.get("max_wait"), 0.0) or None
                cost = a.get("cost_per_hour")
                self.units[c.id] = Unit(
                    id=c.id, capacity=capacity, service_time=_num(a.get("service_time"), 1.0),
                    max_wait=max_wait, crowd=crowd, hold=bool(a.get("hold_bed_while_waiting", False)),
                    cost_per_hour=_num(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool)
                    else None,
                )
            self.status[c.id] = Status.HEALTHY
            self.timeline[c.id] = [(0.0, Status.HEALTHY)]
        for d in self.system.dependencies:
            self.routes.setdefault(d.source_id, []).append((d.target_id, _num(d.attributes.get("probability"), 1.0)))
        for u in self.units:
            self.series["queue"][u] = []
            self.series["in_use"][u] = []

    # ---- patients -----------------------------------------------------------
    def _schedule_arrival(self, source_id: str) -> None:
        src = self.sources[source_id]
        rate = src["rate"] * src["multiplier"]
        if rate <= 0:
            return
        gap = self.kernel.stream(f"arrivals:{source_id}").expovariate(rate)
        self.kernel.after(gap, "arrive", source_id, data={"version": src["version"]}, priority=P_FLOW)

    def _new_patient(self, source_id: str) -> Patient:
        src = self.sources[source_id]
        src["count"] += 1
        if len(self.patients) >= MAX_PATIENTS:
            raise ValueError(f"more than {MAX_PATIENTS} patients in one run; lower the rate or the time window")
        p = Patient(len(self.patients), self.kernel.now, random.Random(f"{self.seed}:patient:{source_id}:{src['count']}"))
        self.patients.append(p)
        return p

    def _next_unit(self, node_id: str, patient: Patient) -> str | None:
        draw = patient.rng.random()
        total = 0.0
        for target, share in self.routes.get(node_id, []):
            total += share
            if draw < total:
                return target
        return None  # the remaining share is discharged

    def _arrive_at(self, patient: Patient, unit_id: str | None, holding: str | None = None) -> None:
        if unit_id is None or unit_id not in self.units:
            self._discharge(patient, holding)
            return
        unit = self.units[unit_id]
        if unit.busy < unit.available and unit.queued == 0:
            self._start(patient, unit, holding)
            return
        entry = QueueEntry(patient, self.kernel.now, holding)
        unit.queue.append(entry)
        unit.queued += 1
        unit.peak_queue = max(unit.peak_queue, unit.queued)
        if holding is None:
            patient.waiting_since = self.kernel.now
            if unit.max_wait:
                self.kernel.after(unit.max_wait, "renege", unit_id, data={"entry": entry}, priority=P_FLOW)
        else:
            patient.boarding_since = self.kernel.now
        self._update_status(unit)

    def _start(self, patient: Patient, unit: Unit, holding: str | None) -> None:
        now = self.kernel.now
        if patient.waiting_since is not None:
            patient.wait += now - patient.waiting_since
            patient.waiting_since = None
        if patient.boarding_since is not None:
            patient.boarding += now - patient.boarding_since
            patient.wait += now - patient.boarding_since
            patient.boarding_since = None
        self._set_busy(unit, unit.busy + 1)
        if holding is not None:
            self._release(self.units[holding])
        service = patient.rng.expovariate(1.0 / unit.service_time) if unit.service_time > 0 else 0.0
        self.kernel.after(service * unit.slowdown, "done", unit.id, data={"patient": patient}, priority=P_FLOW)
        self._update_status(unit)

    def _done(self, patient: Patient, unit: Unit) -> None:
        nxt = self._next_unit(unit.id, patient)
        if nxt is None or nxt not in self.units:
            self._discharge(patient, unit.id)
            return
        target = self.units[nxt]
        if unit.hold and not (target.busy < target.available and target.queued == 0):
            self._arrive_at(patient, nxt, holding=unit.id)  # boards: keeps this bed
        else:
            self._release(unit)
            self._arrive_at(patient, nxt)

    def _discharge(self, patient: Patient, holding: str | None) -> None:
        patient.done = True
        if not patient.preexisting:
            self.discharged_los.append(self.kernel.now - patient.arrived)
        if holding is not None:
            self._release(self.units[holding])

    def _release(self, unit: Unit) -> None:
        self._set_busy(unit, unit.busy - 1)
        self._pull(unit)

    def _pull(self, unit: Unit) -> None:
        while unit.busy < unit.available and unit.queue:
            entry = unit.queue.popleft()
            if not entry.active:
                continue
            entry.active = False
            unit.queued -= 1
            self._start(entry.patient, unit, entry.holding)
        self._update_status(unit)

    def _renege(self, unit: Unit, entry: QueueEntry) -> None:
        if not entry.active:
            return
        entry.active = False
        unit.queued -= 1
        p = entry.patient
        if p.waiting_since is not None:
            p.wait += self.kernel.now - p.waiting_since
            p.waiting_since = None
        p.done = True
        if not p.preexisting:
            self.left += 1
        self._update_status(unit)

    def _set_busy(self, unit: Unit, busy: int) -> None:
        now = self.kernel.now
        unit.busy_area += unit.busy * (now - unit.last_change)
        unit.last_change = now
        unit.busy = busy

    # ---- disruptions --------------------------------------------------------
    def _event(self, item, starting: bool) -> None:
        etype, sev, target = item.data["type"], float(item.data["severity"]), item.component_id
        verb = "begins" if starting else "ends"
        entry = self.kernel.log_entry(kind="event", component_id=target, event_id=item.event_id,
                                      message=f"{etype.replace('_', ' ')} {verb}")
        if etype == "arrival_surge" and target in self.sources:
            src = self.sources[target]
            src["multiplier"] = src["multiplier"] * sev if starting else src["multiplier"] / sev
            src["version"] += 1
            self._schedule_arrival(target)  # memoryless: restart the arrival clock at the new rate
            if starting:
                self.surge_causes.append(entry.id)
            elif self.surge_causes:
                self.surge_causes.pop(0)
            self._set_status(target, Status.DEGRADED if src["multiplier"] > 1 else Status.HEALTHY,
                             f"arrivals x{src['multiplier']:g}", entry.id)
            return
        unit = self.units.get(target)
        if unit is None:
            return
        if etype == "staff_shortage":
            unit.unavailable += sev if starting else -sev
        elif etype == "unit_closure":
            unit.closed += 1 if starting else -1
        elif etype == "service_slowdown":
            unit.slowdown = unit.slowdown * sev if starting else unit.slowdown / sev
        if starting:
            unit.causes.append(entry.id)
        elif unit.causes:
            unit.causes.pop(0)
        self._pull(unit)
        self._update_status(unit, cause=entry.id)

    # ---- statuses -----------------------------------------------------------
    def _update_status(self, unit: Unit, cause: int | None = None) -> None:
        q, crowd = unit.queued, unit.crowd
        old = self.status[unit.id]
        closed_with_queue = unit.available == 0 and q > 0
        if closed_with_queue or q >= 3 * crowd:
            new = Status.FAILED
        elif old == Status.FAILED and q > 2 * crowd:
            new = Status.FAILED  # hysteresis: stay failed until the queue is clearly smaller
        elif q >= crowd:
            new = Status.DEGRADED
        elif old >= Status.DEGRADED and q > crowd / 2:
            new = Status.DEGRADED
        else:
            new = Status.HEALTHY
        if new == old:
            return
        if closed_with_queue:
            reason = f"no beds/staff available, {q} waiting"
        elif new == Status.HEALTHY:
            reason = f"queue down to {q}"
        else:
            reason = f"queue {q} (crowded at {crowd})"
        self._set_status(unit.id, new, reason, cause if cause is not None else self._cause_for(unit))

    def _cause_for(self, unit: Unit) -> int | None:
        if unit.causes:
            return unit.causes[-1]
        # Patients boarding here are waiting for a crowded unit downstream.
        for target, _share in (self.routes.get(unit.id, []) if unit.hold else []):
            if target in self.units and self.status[target] != Status.HEALTHY and target in self.status_entry:
                return self.status_entry[target]
        return self.surge_causes[-1] if self.surge_causes else None

    def _set_status(self, node_id: str, new: Status, reason: str, cause: int | None) -> None:
        old = self.status[node_id]
        if new == old:
            return
        self.status[node_id] = new
        tl = self.timeline[node_id]
        if tl[-1][0] == self.kernel.now:
            tl[-1] = (self.kernel.now, new)
            if len(tl) > 1 and tl[-2][1] == new:
                tl.pop()
        else:
            tl.append((self.kernel.now, new))
        suffix = "" if cause is not None or new == Status.HEALTHY else " (normal variation)"
        entry = self.kernel.log_entry(kind="status_change", component_id=node_id, cause_id=cause,
                                      message=f"{old} -> {new}: {reason}{suffix}", old_status=old, new_status=new)
        self.status_entry[node_id] = entry.id

    # ---- main loop ----------------------------------------------------------
    def _handle(self, item) -> None:
        kind = item.kind
        if kind == "arrive":
            src = self.sources[item.component_id]
            if item.data["version"] != src["version"]:
                return  # superseded by a rate change
            patient = self._new_patient(item.component_id)
            self._schedule_arrival(item.component_id)
            self._arrive_at(patient, self._next_unit(item.component_id, patient))
        elif kind == "done":
            self._done(item.data["patient"], self.units[item.component_id])
        elif kind == "renege":
            self._renege(self.units[item.component_id], item.data["entry"])
        elif kind == "start":
            self._event(item, True)
        elif kind == "end":
            self._event(item, False)
        elif kind == "sample":
            t = self.kernel.now
            for u in self.units.values():
                self.series["queue"][u.id].append([t, u.queued])
                self.series["in_use"][u.id].append([t, u.busy])

    # ---- results ------------------------------------------------------------
    def _outcome(self) -> dict:
        until = self.until
        for u in self.units.values():
            self._set_busy(u, u.busy)  # close the utilisation integral at `until`
        totals = []
        boarding = 0.0
        for p in self.initial:  # their boarding still blocks beds, so it counts
            boarding += p.boarding + ((until - p.boarding_since) if p.boarding_since is not None else 0.0)
        for p in self.patients:
            wait = p.wait
            if p.waiting_since is not None:
                wait += until - p.waiting_since
            if p.boarding_since is not None:
                wait += until - p.boarding_since
            totals.append(wait)
            boarding += p.boarding + ((until - p.boarding_since) if p.boarding_since is not None else 0.0)
        arrived = len(self.patients)
        util = [u.busy_area / (u.capacity * until) for u in self.units.values() if u.capacity > 0]
        unit_timelines = [self.timeline[u] for u in self.units]
        crowded = 0.0
        if unit_timelines:
            merged = time_in_status(worst_of(unit_timelines), until)
            crowded = merged[Status.DEGRADED] + merged[Status.FAILED]
        costs = [u.capacity * u.cost_per_hour * until for u in self.units.values() if u.cost_per_hour is not None]
        staff_cost = round(sum(costs), 4) if costs else None
        metrics = {
            "mean_wait": round(sum(totals) / arrived, 4) if arrived else 0.0,
            "p95_wait": round(percentile(totals, 95), 4) if totals else 0.0,
            "left_without_treatment": self.left,
            "left_rate": round(self.left / arrived, 4) if arrived else 0.0,
            "patients_treated": len(self.discharged_los),
            "mean_length_of_stay": round(sum(self.discharged_los) / len(self.discharged_los), 4)
            if self.discharged_los else None,
            "boarding_time": round(boarding, 4),
            "peak_queue": max((u.peak_queue for u in self.units.values()), default=0),
            "bottleneck_utilisation": round(max(util), 4) if util else None,
            "crowded_time": round(crowded, 4),
            "patients_arrived": arrived,
            "staff_cost": staff_cost,
        }
        return metrics


class HospitalDomain(Domain):
    spec = HOSPITAL_SPEC

    def errors(self, system: System) -> list[str]:
        problems = super().errors(system)
        shares: dict[str, float] = {}
        for d in system.dependencies:
            p = d.attributes.get("probability", 1.0)
            if not isinstance(p, (int, float)) or isinstance(p, bool) or not 0 <= p <= 1:
                problems.append(f"Route {d.id}: share of patients must be between 0 and 1")
                continue
            shares[d.source_id] = shares.get(d.source_id, 0.0) + float(p)
            target = system.components.get(d.target_id)
            if target is not None and target.type == "arrivals":
                problems.append(f"Route {d.id}: patients cannot be routed into an arrivals node")
        for source, total in shares.items():
            if total > 1 + 1e-9:
                problems.append(f"Routes from {source} send {total:.0%} of patients; the shares must add up to at most 100%")
        for c in system.components.values():
            a = c.attributes
            if c.type in UNIT_TYPES:
                if _num(a.get("capacity"), 1) < 0:
                    problems.append(f"Unit {c.id}: beds/staff cannot be negative")
                if _num(a.get("service_time"), 1) <= 0:
                    problems.append(f"Unit {c.id}: mean time in unit must be above 0")
            if c.type == "arrivals" and _num(a.get("rate"), 0) < 0:
                problems.append(f"Arrivals {c.id}: rate cannot be negative")
        if not any(c.type == "arrivals" for c in system.components.values()) and system.components:
            problems.append("Add a 'Patient arrivals' node so patients enter the hospital")
        return problems

    def validate(self, system: System) -> list[str]:
        warnings = []
        sources = {d.source_id for d in system.dependencies}
        for c in system.components.values():
            if c.type == "arrivals" and c.id not in sources:
                warnings.append(f"{c.name} has no route, so its patients go nowhere")
        return warnings

    def simulate(self, system: System, events: list[Event], until: float, seed: int,
                 *, intervention_cost: float = 0.0) -> Outcome:
        rate_total = sum(_num(c.attributes.get("rate"), 0.0) for c in system.components.values()
                         if c.type == "arrivals")
        surge = max([e.severity for e in events if e.type == "arrival_surge"] + [1.0])
        if rate_total * surge * until > MAX_PATIENTS:
            raise ValueError(f"about {rate_total * surge * until:,.0f} patients in one run is more than the "
                             f"{MAX_PATIENTS:,} limit; shorten the window or lower the rates")
        model = HospitalModel(system, events, until, seed)
        model.kernel.run(model._handle)
        metrics = model._outcome()
        metrics["cost"] = intervention_cost
        metrics["total_cost"] = None if metrics["staff_cost"] is None else round(metrics["staff_cost"] + intervention_cost, 4)
        return Outcome(
            metrics=MetricValues(metrics),
            log=model.kernel.log,
            timelines=model.timeline,
            series=model.series,
            skipped_events=model.skipped,
            state=model,
        )
