"""Import and export whole experiments (system + scenario tree) as JSON."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..schemas import ExperimentIn, ImportOut, ScenarioIn, SystemIn
from . import scenarios, systems
from .errors import InvalidInput


def import_experiment(db: Session, data: ExperimentIn) -> ImportOut:
    system_in = SystemIn(**data.system.model_dump(exclude={"id"}))
    system_row = systems.create(db, system_in)
    id_map: dict[str, str] = {}
    try:
        for s in data.scenarios:
            parent_ref = s.parent or s.parent_id
            if parent_ref is not None and parent_ref not in id_map:
                raise InvalidInput(f"Scenario {s.id!r}: parent {parent_ref!r} must be defined before it")
            payload = s.model_dump(exclude={"id", "parent", "parent_id"})
            row = scenarios.create(db, system_row.id,
                                   ScenarioIn(**payload, parent_id=id_map.get(parent_ref) if parent_ref else None))
            id_map[s.id] = row.id
    except Exception:
        # Do not leave a half-imported experiment behind.
        systems.delete(db, system_row.id)
        raise
    return ImportOut(system_id=system_row.id, scenario_ids=id_map)


def export_experiment(db: Session, system_id: str, until: float = 30.0) -> dict:
    row = systems.get(db, system_id)
    out_scenarios = []
    for s in sorted(row.scenarios, key=_depth):  # parents before children
        out = scenarios.to_schema(s)
        out_scenarios.append({
            "id": out.id,
            "name": out.name,
            "description": out.description,
            "parent": out.parent_id,
            "seed": out.seed,
            "events": [e.model_dump() for e in out.events],
            "interventions": [i.model_dump() for i in out.interventions],
            "remove_events": out.remove_events,
        })
    return {
        "until": until,
        "system": {"id": row.id, **systems.to_input(row).model_dump()},
        "scenarios": out_scenarios,
    }


def _depth(s) -> tuple[int, object]:
    depth, cur = 0, s.parent
    while cur is not None:
        depth, cur = depth + 1, cur.parent
    return depth, s.created_at
