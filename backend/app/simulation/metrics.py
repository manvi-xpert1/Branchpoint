"""Turn a finished run into comparable numbers.

All durations are in simulated time units over the window [0, until].
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..models import Status
from .state import SimulationState


@dataclass
class Metrics:
    duration: float
    availability: float  # fraction of time the entry points were not FAILED
    downtime: float  # time any entry point was FAILED
    degraded_time: float  # time the worst entry point was DEGRADED
    affected_components: int  # components that left HEALTHY at any point
    recovery_time: float | None  # first problem -> everything healthy again; None if never
    cost: float = 0.0

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

    return Metrics(
        duration=until,
        availability=round(1 - service_time[Status.FAILED] / until, 4),
        downtime=service_time[Status.FAILED],
        degraded_time=service_time[Status.DEGRADED],
        affected_components=affected,
        recovery_time=recovery_time,
        cost=cost,
    )
