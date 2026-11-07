"""Cold-chain logistics: stock, orders, shipments and refrigeration on the shared kernel.

How one run works
-----------------
* Every hour each **store** sells to customers: demand is random
  (Poisson) at its ``demand_rate``, oldest stock first. Unmet demand is lost.
* Every hour each site with a reorder point checks its **inventory
  position** (on hand + on order). At or below ``reorder_point`` it orders
  ``order_quantity`` units (an (s, Q) policy).
* An order is filled by the source that can deliver **fastest over open
  routes**: Dijkstra's algorithm runs backwards from the ordering site over
  ``ships_to`` routes that are not closed. A source is a site with enough
  stock on hand, or a supplier (which adds its dispatch lead time). The
  stock leaves immediately and arrives after the path's total travel time.
* The **planned** delivery time is the same calculation with every route
  open and no supplier delays. Arriving later than planned counts as late,
  and the order is logged with the closure or delay that caused it.
* **Exposure.** During a ``power_outage``, once a site's backup power runs
  out, every unit on site accumulates exposure time. During a
  ``reefer_failure``, shipments travelling on that route accumulate the
  overlap. On an unrefrigerated route the whole trip counts. A batch whose
  exposure exceeds the ``max_excursion_hours`` parameter is **discarded**:
  that is the user's rule, not a safety judgement by Branchpoint.

Statuses: a store is FAILED while out of stock and DEGRADED while its
stock is exposed; a warehouse or distribution centre is DEGRADED while
exposed or empty. Routes have statuses too (FAILED closed, DEGRADED
refrigeration failure), keyed by route id.
"""

from __future__ import annotations

import heapq
import math
import random
from collections import deque
from dataclasses import dataclass, field

from ...models import Event, Status, System
from ...simulation.kernel import Kernel
from ...simulation.metrics import time_in_status
from ...simulation.outcome import MetricValues, Outcome
from ..base import Domain
from .spec import COLDCHAIN_SPEC

STOCK_TYPES = {"warehouse", "distribution", "store"}
P_END, P_START, P_FLOW, P_TICK = 0, 1, 2, 3
MAX_HOURS = 24 * 365 * 2  # two simulated years per run at most


def _num(value, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def poisson(rng: random.Random, lam: float) -> int:
    """Poisson random number: Knuth's method for small means, a normal approximation for large ones."""
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


@dataclass
class Batch:
    qty: int
    exposure: float = 0.0
    cause: int | None = None  # log id of what exposed it most recently


@dataclass
class Site:
    id: str
    type: str
    batches: deque = field(default_factory=deque)
    reorder_point: float | None = None
    order_quantity: int = 0
    demand_rate: float = 0.0
    demand_multiplier: float = 1.0
    holding_cost: float = 0.0
    backup_hours: float = 0.0
    lead_time: float = 0.0
    lead_multiplier: float = 1.0
    on_order: int = 0
    outages: list = field(default_factory=list)  # [start time, log id] of active outages
    last_accrue: float = 0.0
    issue: int | None = None  # log id of the latest problem affecting this site
    delay_cause: int | None = None  # supplier: active delay log id

    @property
    def on_hand(self) -> int:
        return sum(b.qty for b in self.batches)


@dataclass
class Route:
    id: str
    source: str
    target: str
    travel_time: float
    cost_per_unit: float
    refrigerated: bool
    closed: list = field(default_factory=list)  # log ids of active closures
    failures: list = field(default_factory=list)  # [start, end | None, log id]


class ColdChainModel:
    def __init__(self, system: System, events: list[Event], until: float, seed: int) -> None:
        self.system, self.until, self.seed = system, until, seed
        self.kernel = Kernel(until, seed, max_steps=5_000_000)
        p = system.parameters
        self.tolerance = _num(p.get("max_excursion_hours"), 2.0)
        self.unit_value = _num(p.get("unit_value"), 10.0)
        self.sites: dict[str, Site] = {}
        self.routes: dict[str, Route] = {}
        self.into: dict[str, list[Route]] = {}
        self.status: dict[str, Status] = {}
        self.timeline: dict[str, list[tuple[float, Status]]] = {}
        self.totals = dict(demand=0, sold=0, lost=0, discarded=0, exposed=0.0, deliveries=0, on_time=0,
                           delivery_time=0.0, reroutes=0, transport=0.0, holding=0.0)
        self.series: dict[str, dict[str, list]] = {"inventory": {}}
        self._build()
        occurring, self.skipped = self.kernel.sample_events(events)
        for e in occurring:
            data = {"type": e.type, "severity": e.severity}
            self.kernel.at(e.start_time, "start", e.target_id, event_id=e.id, data=data, priority=P_START)
            if e.duration is not None:
                self.kernel.at(e.start_time + e.duration, "end", e.target_id, event_id=e.id, data=data,
                               priority=P_END)
        hours = int(math.floor(until))
        self.sample_every = max(1, hours // 150)
        for h in range(hours + 1):
            self.kernel.at(float(h), "tick", "", data={"hour": h}, priority=P_TICK)

    # ---- set-up -------------------------------------------------------------
    def _build(self) -> None:
        for c in self.system.components.values():
            a = c.attributes
            site = Site(c.id, c.type)
            if c.type == "supplier":
                site.lead_time = _num(a.get("lead_time"), 24.0)
            else:
                start = int(_num(a.get("inventory"), 0))
                if start > 0:
                    site.batches.append(Batch(start))
                rp = a.get("reorder_point")
                site.reorder_point = _num(rp) if isinstance(rp, (int, float)) and not isinstance(rp, bool) else None
                site.order_quantity = max(1, int(_num(a.get("order_quantity"), 1)))
                site.demand_rate = _num(a.get("demand_rate"), 0.0) if c.type == "store" else 0.0
                site.holding_cost = _num(a.get("holding_cost"), 0.0)
                site.backup_hours = _num(a.get("backup_power_hours"), 0.0)
                self.series["inventory"][c.id] = []
            self.sites[c.id] = site
            self.status[c.id] = Status.HEALTHY
            self.timeline[c.id] = [(0.0, Status.HEALTHY)]
        for d in self.system.dependencies:
            a = d.attributes
            r = Route(d.id, d.source_id, d.target_id, _num(a.get("travel_time"), 6.0),
                      _num(a.get("cost_per_unit"), 0.0), bool(a.get("refrigerated", True)))
            self.routes[d.id] = r
            self.into.setdefault(d.target_id, []).append(r)
            self.status[d.id] = Status.HEALTHY
            self.timeline[d.id] = [(0.0, Status.HEALTHY)]

    # ---- statuses -----------------------------------------------------------
    def _set_status(self, key: str, new: Status, reason: str, cause: int | None) -> None:
        old = self.status[key]
        if new == old:
            return
        self.status[key] = new
        tl = self.timeline[key]
        if tl[-1][0] == self.kernel.now:
            tl[-1] = (self.kernel.now, new)
            if len(tl) > 1 and tl[-2][1] == new:
                tl.pop()
        else:
            tl.append((self.kernel.now, new))
        self.kernel.log_entry(kind="status_change", component_id=key, cause_id=cause,
                              message=f"{old} -> {new}: {reason}", old_status=old, new_status=new)

    def _exposed(self, site: Site, at: float | None = None) -> bool:
        t = self.kernel.now if at is None else at
        return any(t >= start + site.backup_hours for start, _ in site.outages)

    def _update_site(self, site: Site) -> None:
        if site.type == "supplier":
            return
        exposed = self._exposed(site)
        cause = site.outages[-1][1] if exposed else site.issue
        if site.type == "store" and site.on_hand == 0:
            self._set_status(site.id, Status.FAILED, "out of stock", cause)
        elif exposed:
            self._set_status(site.id, Status.DEGRADED, "stock exposed: power outage beyond backup", cause)
        elif site.type != "store" and site.on_hand == 0:
            self._set_status(site.id, Status.DEGRADED, "empty", cause)
        else:
            self._set_status(site.id, Status.HEALTHY, f"{site.on_hand} units on hand", None)

    # ---- stock accounting ---------------------------------------------------
    def _accrue(self, site: Site) -> None:
        """Bring holding cost and outage exposure up to now, then discard over-exposed batches."""
        now, last = self.kernel.now, site.last_accrue
        if now <= last:
            return
        on_hand = site.on_hand
        self.totals["holding"] += on_hand * site.holding_cost * (now - last)
        for start, cause in site.outages:
            seg = now - max(last, start + site.backup_hours)
            if seg > 0:
                for b in site.batches:
                    b.exposure += seg
                    b.cause = cause
                self.totals["exposed"] += on_hand * seg
        site.last_accrue = now
        self._discard(site)

    def _discard(self, site: Site) -> None:
        keep = deque()
        for b in site.batches:
            if b.exposure > self.tolerance + 1e-9:
                self.totals["discarded"] += b.qty
                entry = self.kernel.log_entry(
                    kind="event", component_id=site.id, cause_id=b.cause,
                    message=f"{b.qty} units discarded: exposure passed the {self.tolerance:g} h tolerance",
                )
                site.issue = entry.id
            else:
                keep.append(b)
        site.batches = keep

    def _take(self, site: Site, qty: int) -> list[Batch]:
        """Remove qty units, oldest first, keeping each batch's exposure."""
        taken = []
        while qty > 0 and site.batches:
            b = site.batches[0]
            n = min(qty, b.qty)
            taken.append(Batch(n, b.exposure, b.cause))
            b.qty -= n
            qty -= n
            if b.qty == 0:
                site.batches.popleft()
        return taken

    # ---- orders -------------------------------------------------------------
    def _paths_to(self, dest: str, use_closures: bool) -> dict[str, tuple[float, list[Route]]]:
        """Fastest travel time (and route list, in travel order) from every site to ``dest``."""
        best: dict[str, tuple[float, list[Route]]] = {dest: (0.0, [])}
        heap = [(0.0, dest)]
        while heap:
            t, node = heapq.heappop(heap)
            if t > best[node][0]:
                continue
            for r in self.into.get(node, []):
                if use_closures and r.closed:
                    continue
                nt = t + r.travel_time
                if r.source not in best or nt < best[r.source][0] - 1e-12:
                    best[r.source] = (nt, [r] + best[node][1])
                    heapq.heappush(heap, (nt, r.source))
        return best

    def _choose(self, dest: str, qty: int, actual: bool) -> tuple[str, float, list[Route]] | None:
        options = []
        for node, (travel, path) in self._paths_to(dest, use_closures=actual).items():
            if node == dest:
                continue
            site = self.sites[node]
            if site.type == "supplier":
                lead = site.lead_time * (site.lead_multiplier if actual else 1.0)
                options.append((travel + lead, node, path))
            elif site.on_hand >= qty:
                options.append((travel, node, path))
        if not options:
            return None
        total, node, path = min(options, key=lambda o: (o[0], o[1]))
        return node, total, path

    def _review(self, site: Site) -> None:
        if site.reorder_point is None or site.type == "supplier":
            return
        if site.on_hand + site.on_order > site.reorder_point:
            return
        qty = site.order_quantity
        choice = self._choose(site.id, qty, actual=True)
        if choice is None:
            if site.issue is None or self.kernel.log[site.issue].message != "no open route can supply this site":
                entry = self.kernel.log_entry(kind="event", component_id=site.id, message="no open route can supply this site",
                                              cause_id=self._closure_cause(site.id))
                site.issue = entry.id
            return
        source_id, total, path = choice
        source = self.sites[source_id]
        planned = self._choose(site.id, qty, actual=False)
        planned_time = planned[1] if planned else total
        if source.type == "supplier":
            batches = [Batch(qty)]
        else:
            self._accrue(source)
            batches = self._take(source, qty)
            self._update_site(source)
        site.on_order += qty
        depart = self.kernel.now + (source.lead_time * source.lead_multiplier if source.type == "supplier" else 0.0)
        legs, t = [], depart
        for r in path:
            legs.append((r, t, t + r.travel_time))
            self.totals["transport"] += qty * r.cost_per_unit
            t += r.travel_time
        late = total > planned_time + 1e-9
        cause = None
        if late:
            self.totals["reroutes"] += 1
            cause = source.delay_cause if source.type == "supplier" else None
            if cause is None:  # log ids start at 0, so test for None explicitly
                cause = self._closure_cause(site.id)
            via = " -> ".join([path[0].source] + [r.target for r in path]) if path else source_id
            entry = self.kernel.log_entry(
                kind="event", component_id=site.id, cause_id=cause,
                message=f"order of {qty} units via {via}: {total:g} h instead of {planned_time:g} h",
            )
            site.issue = entry.id
        self.kernel.at(t, "arrive", site.id, priority=P_FLOW,
                       data={"batches": batches, "legs": legs, "qty": qty, "ordered": self.kernel.now,
                             "planned": planned_time, "late": late})

    def _closure_cause(self, dest: str) -> int | None:
        for r in self.into.get(dest, []):
            if r.closed:
                return r.closed[-1]
        for r in self.routes.values():
            if r.closed:
                return r.closed[-1]
        return None

    def _arrive(self, site: Site, data: dict) -> None:
        self._accrue(site)
        for r, dep, arr in data["legs"]:
            if not r.refrigerated:
                exposure, cause = arr - dep, None
            else:
                exposure, cause = 0.0, None
                for start, end, log_id in r.failures:
                    overlap = min(arr, end if end is not None else arr) - max(dep, start)
                    if overlap > 0:
                        exposure += overlap
                        cause = log_id
            if exposure > 0:
                for b in data["batches"]:
                    b.exposure += exposure
                    b.cause = cause if cause is not None else b.cause
                self.totals["exposed"] += data["qty"] * exposure
        site.batches.extend(data["batches"])
        site.on_order -= data["qty"]
        self.totals["deliveries"] += 1
        self.totals["delivery_time"] += self.kernel.now - data["ordered"]
        if not data["late"]:
            self.totals["on_time"] += 1
        self._discard(site)
        self._update_site(site)

    # ---- disruptions --------------------------------------------------------
    def _event(self, item, starting: bool) -> None:
        etype, sev, target = item.data["type"], float(item.data["severity"]), item.component_id
        entry = self.kernel.log_entry(kind="event", component_id=target, event_id=item.event_id,
                                      message=f"{etype.replace('_', ' ')} {'begins' if starting else 'ends'}")
        if etype in ("reefer_failure", "route_closure"):
            r = self.routes.get(target)
            if r is None:
                return
            if etype == "route_closure":
                if starting:
                    r.closed.append(entry.id)
                elif r.closed:
                    r.closed.pop(0)
            elif starting:
                r.failures.append([self.kernel.now, None, entry.id])
            else:
                for f in r.failures:
                    if f[1] is None:
                        f[1] = self.kernel.now
                        break
            active_failure = any(f[1] is None for f in r.failures)
            if r.closed:
                self._set_status(r.id, Status.FAILED, "closed", r.closed[-1])
            elif active_failure:
                self._set_status(r.id, Status.DEGRADED, "refrigeration failure", entry.id)
            else:
                self._set_status(r.id, Status.HEALTHY, "open and refrigerated", None)
            return
        site = self.sites.get(target)
        if site is None:
            return
        self._accrue(site)
        if etype == "demand_spike":
            site.demand_multiplier = site.demand_multiplier * sev if starting else site.demand_multiplier / sev
            if starting:
                site.issue = entry.id
        elif etype == "supplier_delay":
            site.lead_multiplier = site.lead_multiplier * sev if starting else site.lead_multiplier / sev
            site.delay_cause = entry.id if starting else None
        elif etype == "power_outage":
            if starting:
                site.outages.append([self.kernel.now, entry.id])
                # Check again when the backup runs out, and just after stock on site passes the tolerance.
                if site.backup_hours > 0:
                    self.kernel.after(site.backup_hours, "backup_out", site.id, priority=P_FLOW)
                self.kernel.after(site.backup_hours + self.tolerance + 1e-6, "backup_out", site.id, priority=P_FLOW)
            elif site.outages:
                site.outages.pop(0)
        self._update_site(site)

    # ---- main loop ----------------------------------------------------------
    def _handle(self, item) -> None:
        kind = item.kind
        if kind == "tick":
            self._tick(item.data["hour"])
        elif kind == "arrive":
            self._arrive(self.sites[item.component_id], item.data)
        elif kind == "start":
            self._event(item, True)
        elif kind == "end":
            self._event(item, False)
        elif kind == "backup_out":
            site = self.sites[item.component_id]
            self._accrue(site)
            self._update_site(site)

    def _tick(self, hour: int) -> None:
        stocked = [s for s in self.sites.values() if s.type in STOCK_TYPES]
        for site in stocked:
            self._accrue(site)
        if hour > 0:  # demand during the hour that just ended
            for site in stocked:
                if site.type != "store":
                    continue
                demand = poisson(self.kernel.stream(f"demand:{site.id}"), site.demand_rate * site.demand_multiplier)
                sold = sum(b.qty for b in self._take(site, demand))
                self.totals["demand"] += demand
                self.totals["sold"] += sold
                self.totals["lost"] += demand - sold
        # Downstream sites review first so they can draw on stock upstream before it is reordered.
        for site in sorted(stocked, key=lambda s: ({"store": 0, "distribution": 1, "warehouse": 2}[s.type], s.id)):
            self._review(site)
        for site in stocked:
            self._update_site(site)
        if hour % self.sample_every == 0:
            for site in stocked:
                self.series["inventory"][site.id].append([float(hour), site.on_hand])

    # ---- results ------------------------------------------------------------
    def metrics(self, intervention_cost: float) -> dict:
        for site in self.sites.values():
            if site.type in STOCK_TYPES:
                self._accrue(site)
        t = self.totals
        stockout = sum(time_in_status(self.timeline[s.id], self.until)[Status.FAILED]
                       for s in self.sites.values() if s.type == "store")
        discard_cost = t["discarded"] * self.unit_value
        handled = t["sold"] + t["discarded"]
        return {
            "fill_rate": round(t["sold"] / t["demand"], 4) if t["demand"] else 1.0,
            "lost_sales": t["lost"],
            "stockout_time": round(stockout, 4),
            "units_discarded": t["discarded"],
            "discard_rate": round(t["discarded"] / handled, 4) if handled else 0.0,
            "exposed_unit_hours": round(t["exposed"], 4),
            "on_time_rate": round(t["on_time"] / t["deliveries"], 4) if t["deliveries"] else None,
            "mean_delivery_time": round(t["delivery_time"] / t["deliveries"], 4) if t["deliveries"] else None,
            "reroutes": t["reroutes"],
            "transport_cost": round(t["transport"], 4),
            "holding_cost": round(t["holding"], 4),
            "discard_cost": round(discard_cost, 4),
            "cost": intervention_cost,
            "total_cost": round(t["transport"] + t["holding"] + discard_cost + intervention_cost, 4),
        }


class ColdChainDomain(Domain):
    spec = COLDCHAIN_SPEC

    def errors(self, system: System) -> list[str]:
        problems = super().errors(system)
        for d in system.dependencies:
            if _num(d.attributes.get("travel_time"), 6.0) <= 0:
                problems.append(f"Route {d.id}: travel time must be above 0")
            target = system.components.get(d.target_id)
            if target is not None and target.type == "supplier":
                problems.append(f"Route {d.id}: suppliers cannot receive shipments")
        for c in system.components.values():
            a = c.attributes
            for key in ("inventory", "reorder_point", "demand_rate", "backup_power_hours", "lead_time"):
                if _num(a.get(key), 0) < 0:
                    problems.append(f"{c.id}: {key.replace('_', ' ')} cannot be negative")
            if c.type in STOCK_TYPES and _num(a.get("order_quantity"), 1) < 1:
                problems.append(f"{c.id}: order size must be at least 1")
        return problems

    def validate(self, system: System) -> list[str]:
        warnings = []
        supplied = {d.target_id for d in system.dependencies}
        for c in system.components.values():
            if c.type in STOCK_TYPES and c.attributes.get("reorder_point") is not None and c.id not in supplied:
                warnings.append(f"{c.name} reorders but no route ships to it")
        if system.components and not any(c.type == "supplier" for c in system.components.values()):
            warnings.append("No supplier: stock can only move between sites, never be replenished")
        return warnings

    def simulate(self, system: System, events: list[Event], until: float, seed: int,
                 *, intervention_cost: float = 0.0) -> Outcome:
        if until > MAX_HOURS:
            raise ValueError(f"the cold-chain model runs at most {MAX_HOURS:,} hours per run")
        model = ColdChainModel(system, events, until, seed)
        model.kernel.run(model._handle)
        return Outcome(
            metrics=MetricValues(model.metrics(intervention_cost)),
            log=model.kernel.log,
            timelines=model.timeline,
            series=model.series,
            skipped_events=model.skipped,
            state=model,
        )
