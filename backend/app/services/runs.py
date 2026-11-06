"""Running scenarios, storing results, replaying and comparing runs."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import ScenarioRow, SimulationEventRow, SimulationRunRow
from ..models import Event, System
from ..schemas import CompareOut, LogEntryOut, Metrics, ReplayOut, RunOut, RunSummary
from ..simulation.branching import Intervention, Scenario, SimulationResult, run_scenario
from ..simulation.engine import SimulationError
from . import scenarios, systems
from .errors import InvalidInput, NotFound


def _simulate(system: System, scenario: Scenario, until: float) -> tuple[SimulationResult, float]:
    started = time.perf_counter()
    try:
        result = run_scenario(system, scenario, until)
    except (SimulationError, ValueError, KeyError) as exc:
        raise InvalidInput(f"Simulation failed: {exc}") from exc
    return result, (time.perf_counter() - started) * 1000


def _timelines(result: SimulationResult) -> dict[str, list[list]]:
    return {cid: [[t, str(s)] for t, s in tl] for cid, tl in result.state.timeline.items()}


def execute(db: Session, scenario_row: ScenarioRow, until: float) -> SimulationRunRow:
    scenario = scenarios.to_domain(scenario_row)
    system = systems.to_domain(scenario_row.system)
    result, elapsed_ms = _simulate(system, scenario, until)

    run = SimulationRunRow(
        scenario=scenario_row,
        status="completed",
        seed=scenario.seed,
        until=until,
        system_snapshot=system.to_dict(),
        scenario_snapshot={
            "name": scenario.name,
            "lineage": scenario.lineage(),
            "seed": scenario.seed,
            "events": [e.to_dict() for e in scenario.resolved_events()],
            "interventions": [
                {"id": i.id, "type": i.type, "params": i.params, "cost": i.cost,
                 "description": i.description}
                for i in scenario.resolved_interventions()
            ],
        },
        metrics=result.metrics.to_dict(),
        skipped_events=result.skipped_events,
        timelines=_timelines(result),
        elapsed_ms=round(elapsed_ms, 3),
    )
    for entry in result.log:
        run.log.append(SimulationEventRow(
            seq=entry.id, time=entry.time, kind=entry.kind, component_key=entry.component_id,
            message=entry.message, cause_seq=entry.cause_id, event_key=entry.event_id,
            old_status=None if entry.old_status is None else str(entry.old_status),
            new_status=None if entry.new_status is None else str(entry.new_status),
        ))
    db.add(run)
    db.commit()
    return run


# ---- queries ----------------------------------------------------------
def get(db: Session, run_id: str) -> SimulationRunRow:
    row = db.get(SimulationRunRow, run_id)
    if row is None:
        raise NotFound(f"Run {run_id!r} not found")
    return row


def list_for_scenario(db: Session, scenario_id: str) -> list[SimulationRunRow]:
    scenarios.get(db, scenario_id)
    return list(db.scalars(
        select(SimulationRunRow).where(SimulationRunRow.scenario_id == scenario_id)
        .order_by(SimulationRunRow.created_at.desc())
    ))


def _log_out(e: SimulationEventRow) -> LogEntryOut:
    return LogEntryOut(seq=e.seq, time=e.time, kind=e.kind, component_id=e.component_key,
                       message=e.message, cause_seq=e.cause_seq, event_id=e.event_key,
                       old_status=e.old_status, new_status=e.new_status)


def to_summary(row: SimulationRunRow) -> RunSummary:
    return RunSummary(
        id=row.id, scenario_id=row.scenario_id,
        scenario_name=row.scenario_snapshot.get("name", ""), status=row.status,
        seed=row.seed, until=row.until, metrics=Metrics(**row.metrics),
        elapsed_ms=row.elapsed_ms, created_at=row.created_at,
    )


def effective_system(row: SimulationRunRow) -> dict:
    """The run's system snapshot with its interventions applied."""
    system = System.from_dict(row.system_snapshot)
    for data in row.scenario_snapshot.get("interventions", []):
        Intervention.from_dict(data).apply(system)
    return system.to_dict()


def to_schema(row: SimulationRunRow) -> RunOut:
    return RunOut(
        **to_summary(row).model_dump(),
        system=effective_system(row),
        skipped_events=list(row.skipped_events or []),
        timelines={k: [tuple(p) for p in v] for k, v in (row.timelines or {}).items()},
        log=[_log_out(e) for e in row.log],
    )


def explain(row: SimulationRunRow, seq: int) -> list[LogEntryOut]:
    """Causal chain from the root event to log entry ``seq``."""
    by_seq = {e.seq: e for e in row.log}
    if seq not in by_seq:
        raise NotFound(f"Run {row.id!r} has no log entry {seq}")
    chain = []
    current: int | None = seq
    while current is not None:
        entry = by_seq[current]
        chain.append(_log_out(entry))
        current = entry.cause_seq
    return list(reversed(chain))


def replay(row: SimulationRunRow) -> ReplayOut:
    """Re-run from the stored snapshot and check the outcome is identical."""
    snap = row.scenario_snapshot
    scenario = Scenario(
        id=row.scenario_id,
        name=snap["name"],
        events=[Event.from_dict(e) for e in snap["events"]],
        interventions=[Intervention.from_dict(i) for i in snap["interventions"]],
        seed=snap["seed"],
    )
    result, _ = _simulate(System.from_dict(row.system_snapshot), scenario, row.until)

    differences: list[str] = []
    for key, value in result.metrics.to_dict().items():
        stored = row.metrics.get(key)
        if stored != value:
            differences.append(f"metric {key}: stored {stored}, replay {value}")
    stored_log = [(e.seq, e.time, e.component_key, e.message) for e in row.log]
    new_log = [(e.id, e.time, e.component_id, e.message) for e in result.log]
    if stored_log != new_log:
        differences.append(f"event log differs ({len(stored_log)} stored vs {len(new_log)} replayed entries)")
    return ReplayOut(run_id=row.id, identical=not differences, differences=differences)


# ---- comparison -------------------------------------------------------
# metric -> True if higher is better
_DIRECTION = {
    "availability": True,
    "downtime": False,
    "degraded_time": False,
    "affected_components": False,
    "recovery_time": False,
    "cost": False,
}


def compare(db: Session, run_ids: list[str] | None, scenario_ids: list[str] | None,
            until: float) -> CompareOut:
    if scenario_ids:
        rows = [execute(db, scenarios.get(db, sid), until) for sid in scenario_ids]
    else:
        rows = [get(db, rid) for rid in run_ids or []]
        if len({r.until for r in rows}) > 1:
            raise InvalidInput("Runs used different durations (until); their metrics are not comparable")
    summaries = [to_summary(r) for r in rows]

    best: dict[str, list[str]] = {}
    for metric, higher in _DIRECTION.items():
        values = {s.id: getattr(s.metrics, metric) for s in summaries}
        if metric == "recovery_time":
            # Only runs that had an incident and recovered are candidates.
            values = {k: v for k, v in values.items()
                      if v is not None
                      and next(s for s in summaries if s.id == k).metrics.affected_components > 0}
        if not values:
            continue
        target = (max if higher else min)(values.values())
        best[metric] = [k for k, v in values.items() if v == target]
    return CompareOut(runs=summaries, best=best)
