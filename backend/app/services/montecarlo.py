"""Monte Carlo batches: run a scenario N times and store the summary."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import MonteCarloRunRow, ScenarioRow
from ..schemas import MonteCarloAggregates, MonteCarloOut
from ..simulation.engine import SimulationError
from ..simulation.montecarlo import run_monte_carlo
from . import scenarios, systems
from .errors import InvalidInput, NotFound


def execute(db: Session, scenario_row: ScenarioRow, runs: int, until: float,
            base_seed: int | None = None) -> MonteCarloRunRow:
    scenario = scenarios.to_domain(scenario_row)
    system = systems.to_domain(scenario_row.system)

    started = time.perf_counter()
    try:
        result = run_monte_carlo(system, scenario, until, runs, base_seed)
    except (SimulationError, ValueError, KeyError) as exc:
        raise InvalidInput(f"Monte Carlo failed: {exc}") from exc
    elapsed_ms = (time.perf_counter() - started) * 1000

    row = MonteCarloRunRow(
        scenario=scenario_row,
        runs=runs,
        base_seed=result.base_seed,
        until=until,
        summary=result.to_dict(),
        scenario_snapshot={
            "name": scenario.name,
            "events": [e.to_dict() for e in scenario.resolved_events()],
            "interventions": [
                {"id": i.id, "type": i.type, "params": i.params, "cost": i.cost}
                for i in scenario.resolved_interventions()
            ],
        },
        elapsed_ms=round(elapsed_ms, 3),
    )
    db.add(row)
    db.commit()
    return row


def get(db: Session, mc_id: str) -> MonteCarloRunRow:
    row = db.get(MonteCarloRunRow, mc_id)
    if row is None:
        raise NotFound(f"Monte Carlo run {mc_id!r} not found")
    return row


def list_for_scenario(db: Session, scenario_id: str) -> list[MonteCarloRunRow]:
    scenarios.get(db, scenario_id)
    return list(db.scalars(
        select(MonteCarloRunRow).where(MonteCarloRunRow.scenario_id == scenario_id)
        .order_by(MonteCarloRunRow.created_at.desc())
    ))


def to_schema(row: MonteCarloRunRow) -> MonteCarloOut:
    s = row.summary
    return MonteCarloOut(
        id=row.id,
        scenario_id=row.scenario_id,
        scenario_name=s["scenario_name"],
        runs=row.runs,
        base_seed=row.base_seed,
        until=row.until,
        deterministic=s["deterministic"],
        aggregates=MonteCarloAggregates(**s["aggregates"]),
        downtimes=s["downtimes"],
        elapsed_ms=row.elapsed_ms,
        created_at=row.created_at,
    )
