"""Turn a finished run into comparable numbers.

All durations are in simulated time units over the window [0, until].

The first six metrics always exist. The others are opt-in and are None
when the system has no data for them, so a run never shows a number that
was not computed from the model:

* latency (``latency`` attribute on components): end-to-end response time
  at the entry points, the component's own latency (x the system parameter
  ``degraded_latency_factor``, default 3, while it is degraded itself, by
  an event or overload, not because of a dependency) plus, for each
  dependency group, the latency of the best member in use;
* ``latency_sla`` system parameter: time the entry latency was above it or
  the service was down;
* utilisation (``capacity``): peak load / capacity over all components;
* running cost (``cost_per_time``): sum over components x duration.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass

from ..models import Status, System
from .state import SimulationState


@dataclass
class Metrics:
    duration: float
    availability: float  # fraction of time the entry points were not FAILED
    downtime: float  # time any entry point was FAILED
    degraded_time: float  # time the worst entry point was DEGRADED
    affected_components: int  # components that left HEALTHY at any point
    recovery_time: float | None  # first problem -> everything healthy again; None if never
    cost: float = 0.0  # intervention cost
    mean_latency: float | None = None
    peak_latency: float | None = None
    sla_breach_time: float | None = None
    peak_utilisation: float | None = None
    running_cost: float | None = None
    total_cost: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def time_in_status(timeline: list[tuple[float, Status]], until: float) -> dict[Status, float]:
    """How long a timeline spent in each status, up to ``until``."""
    totals = {s: 0.0 for s in Status}
    for i, (start, status) in enumerate(timeline):
        end = timeline[i + 1][0] if i + 1 < len(timeline) else until
        totals[status] += max(0.0, min(end, until) - min(start, until))
    return totals


def worst_of(timelines: list[list[tuple[float, Status]]]) -> list[tuple[float, Status]]:
    """Merge several timelines into one that shows the worst status at each moment."""
    times = sorted({t for tl in timelines for t, _ in tl})
    merged: list[tuple[float, Status]] = []
    for t in times:
        worst = max(_status_at(tl, t) for tl in timelines)
        if not merged or merged[-1][1] != worst:
            merged.append((t, worst))
    return merged


def _status_at(timeline: list[tuple[float, Status]], t: float) -> Status:
    current = timeline[0][1]
    for time, status in timeline:
        if time > t:
            break
        current = status
    return current


def compute_metrics(state: SimulationState, until: float, cost: float = 0.0) -> Metrics:
    comps = state.system.components
    entry_ids = [c.id for c in comps.values() if c.entry_point] or list(comps)

    service = worst_of([state.timeline[c] for c in entry_ids])
    service_time = time_in_status(service, until)

    affected = sum(1 for tl in state.timeline.values() if any(s != Status.HEALTHY for _, s in tl))

    overall = worst_of(list(state.timeline.values()))
    recovery_time = None
    first_bad = next((t for t, s in overall if s != Status.HEALTHY), None)
    if first_bad is not None and overall[-1][1] == Status.HEALTHY and overall[-1][0] <= until:
        recovery_time = overall[-1][0] - first_bad

    latency = entry_latency_series(state, until)
    mean_latency = peak_latency = sla_breach = None
    if latency is not None:
        total = sum(length for length, v in _segments(latency, until) if v is not None)
        if total > 0:
            mean_latency = round(sum(length * v for length, v in _segments(latency, until) if v is not None) / total, 4)
        values = [v for _, v in latency if v is not None]
        peak_latency = max(values) if values else None
        sla = _number(state.system.parameters.get("latency_sla"))
        if sla is not None:
            sla_breach = sum(length for length, v in _segments(latency, until) if v is None or v > sla)

    running = None
    rates = [_number(c.attributes.get("cost_per_time")) for c in comps.values()]
    if any(r is not None for r in rates):
        running = round(sum(r or 0.0 for r in rates) * until, 4)

    return Metrics(
        duration=until,
        availability=round(1 - service_time[Status.FAILED] / until, 4),
        downtime=service_time[Status.FAILED],
        degraded_time=service_time[Status.DEGRADED],
        affected_components=affected,
        recovery_time=recovery_time,
        cost=cost,
        mean_latency=mean_latency,
        peak_latency=peak_latency,
        sla_breach_time=sla_breach,
        peak_utilisation=peak_utilisation(state),
        running_cost=running,
        total_cost=None if running is None else round(cost + running, 4),
    )


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _segments(points: list[tuple[float, float | None]], until: float):
    """(length, value) for each step of a step function, clipped to [0, until]."""
    for i, (start, value) in enumerate(points):
        end = points[i + 1][0] if i + 1 < len(points) else until
        length = max(0.0, min(end, until) - min(start, until))
        if length > 0:
            yield length, value


def peak_utilisation(state: SimulationState) -> float | None:
    """Highest load / capacity reached by any component with a capacity, or None."""
    peaks = []
    for cid, timeline in state.load.items():
        capacity = _number(state.system.components[cid].attributes.get("capacity"))
        if capacity and capacity > 0:
            peaks.append(max(load for _, load in timeline) / capacity)
    return round(max(peaks), 4) if peaks else None


def entry_latency_series(state: SimulationState, until: float) -> list[tuple[float, float | None]] | None:
    """End-to-end latency at the entry points over time (worst entry point), or None.

    None as a value means the entry points were all failed (no response).
    Returns None overall when no component has a ``latency`` attribute.
    """
    system = state.system
    if not any(_number(c.attributes.get("latency")) is not None for c in system.components.values()):
        return None
    factor = _number(system.parameters.get("degraded_latency_factor")) or 3.0
    entry_ids = [c.id for c in system.components.values() if c.entry_point] or list(system.components)
    groups = dependency_groups(system)
    timelines = list(state.timeline.values()) + list(state.intrinsic.values())
    times = sorted({t for tl in timelines for t, _ in tl if t < until} | {0.0})
    series: list[tuple[float, float | None]] = []
    for t in times:
        statuses = {cid: _status_at(tl, t) for cid, tl in state.timeline.items()}
        slow = {cid for cid, tl in state.intrinsic.items() if _status_at(tl, t) == Status.DEGRADED}
        memo: dict[str, float | None] = {}
        values = [v for v in (latency_at(system, groups, statuses, cid, factor, memo, slow) for cid in entry_ids)
                  if v is not None]
        value = round(max(values), 4) if values else None
        if not series or series[-1][1] != value:
            series.append((t, value))
    return series


def dependency_groups(system: System) -> dict[str, list[list]]:
    """source id -> its dependency groups (lists of Dependency)."""
    by_source: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for dep in system.dependencies:
        by_source[dep.source_id][dep.group or dep.id].append(dep)
    return {src: list(g.values()) for src, g in by_source.items()}


def latency_at(system: System, groups: dict[str, list[list]], statuses: dict[str, Status],
               component_id: str, factor: float, memo: dict[str, float | None],
               slow: set[str] | None = None, _visiting: frozenset = frozenset()) -> float | None:
    """Latency of one request through ``component_id`` given everyone's status, or None if failed.

    Own latency (x ``factor`` when the component itself is slow, i.e. in
    ``slow``; defaults to its effective status being degraded) plus, for each dependency
    group, the latency of the member a request would use: the healthiest
    working member, then the fastest. Failed optional members add nothing.
    """
    if component_id in memo:
        return memo[component_id]
    if statuses[component_id] == Status.FAILED:
        memo[component_id] = None
        return None
    own = _number(system.components[component_id].attributes.get("latency")) or 0.0
    is_slow = component_id in slow if slow is not None else statuses[component_id] == Status.DEGRADED
    total = own * (factor if is_slow else 1.0)
    for members in groups.get(component_id, []):
        best = None
        for dep in members:
            if dep.target_id in _visiting or dep.target_id == component_id:
                continue  # cycle: don't count it twice
            lat = latency_at(system, groups, statuses, dep.target_id, factor, memo, slow,
                             _visiting | {component_id})
            if lat is not None and (best is None or (statuses[dep.target_id], lat) < best):
                best = (statuses[dep.target_id], lat)
        if best is not None:
            total += best[1]
    memo[component_id] = total
    return total
