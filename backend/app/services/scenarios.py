"""Scenario CRUD, inheritance and validation."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import InterventionRow, ScenarioEventRow, ScenarioRow
from ..models import Event, ValidationError
from ..schemas import EventIn, InterventionIn, ScenarioIn, ScenarioOut
from ..simulation.branching import Intervention, Scenario
from . import systems
from .errors import Conflict, InvalidInput, NotFound

DEFAULT_SEED = 42


# ---- conversion -------------------------------------------------------
def _event_in(e: ScenarioEventRow) -> EventIn:
    return EventIn(id=e.key, type=e.type, target_id=e.target_key, start_time=e.start_time,
                   duration=e.duration, severity=e.severity, probability=e.probability)


def _intervention_in(i: InterventionRow) -> InterventionIn:
    return InterventionIn(id=i.key, type=i.type, params=i.params or {}, cost=i.cost,
                          description=i.description)


def to_domain(row: ScenarioRow) -> Scenario:
    """Rebuild the domain Scenario, including its chain of ancestors."""
    try:
        return Scenario(
            id=row.id,
            name=row.name,
            events=[Event.from_dict(_event_in(e).model_dump()) for e in row.events],
            interventions=[Intervention.from_dict(_intervention_in(i).model_dump())
                           for i in row.interventions],
            parent=to_domain(row.parent) if row.parent else None,
            remove_event_ids=list(row.remove_event_ids or []),
            seed=row.seed,
        )
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc


def to_schema(row: ScenarioRow) -> ScenarioOut:
    domain = to_domain(row)
    return ScenarioOut(
        id=row.id,
        system_id=row.system_id,
        parent_id=row.parent_id,
        name=row.name,
        description=row.description,
        seed=row.seed,
        events=[_event_in(e) for e in row.events],
        interventions=[_intervention_in(i) for i in row.interventions],
        remove_events=list(row.remove_event_ids or []),
        children=[c.id for c in row.children],
        lineage=domain.lineage(),
        resolved_events=[EventIn(**e.to_dict()) for e in domain.resolved_events()],
        resolved_interventions=[
            InterventionIn(id=i.id, type=i.type, params=i.params, cost=i.cost, description=i.description)
            for i in domain.resolved_interventions()
        ],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---- validation -------------------------------------------------------
def check(row: ScenarioRow) -> None:
    """Dry-run everything except the simulation itself.

    Applies the resolved interventions to a copy of the system and checks
    that the result is valid and every event targets a real component.
    Also checks every descendant, since they inherit from this scenario.
    """
    scenario = to_domain(row)
    system = systems.to_domain(row.system)
    label = f"Scenario {row.name!r}"
    for intervention in scenario.resolved_interventions():
        try:
            intervention.apply(system)
        except (KeyError, ValueError, ValidationError) as exc:
            raise InvalidInput(f"{label}: intervention {intervention.id!r} cannot be applied: {exc}") from exc
    try:
        system.validate()
    except ValidationError as exc:
        raise InvalidInput(f"{label}: interventions leave an invalid system. {exc}") from exc

    inherited = {e.id for e in scenario.parent.resolved_events()} if scenario.parent else set()
    for eid in scenario.remove_event_ids:
        if eid not in inherited:
            raise InvalidInput(f"{label}: remove_events lists {eid!r}, which no ancestor defines")
    for event in scenario.resolved_events():
        if event.target_id not in system.components:
            raise InvalidInput(f"{label}: event {event.id!r} targets unknown component {event.target_id!r}")

    for child in row.children:
        check(child)


# ---- queries ----------------------------------------------------------
def get(db: Session, scenario_id: str) -> ScenarioRow:
    row = db.get(ScenarioRow, scenario_id)
    if row is None:
        raise NotFound(f"Scenario {scenario_id!r} not found")
    return row


def list_for_system(db: Session, system_id: str) -> list[ScenarioRow]:
    systems.get(db, system_id)
    return list(db.scalars(
        select(ScenarioRow).where(ScenarioRow.system_id == system_id).order_by(ScenarioRow.created_at)
    ))


# ---- commands ---------------------------------------------------------
def _set_parent(db: Session, row: ScenarioRow, parent_id: str | None) -> None:
    if parent_id is None:
        row.parent = None
        return
    parent = get(db, parent_id)
    if parent.system is not row.system:
        raise InvalidInput("Parent scenario belongs to a different system")
    ancestor: ScenarioRow | None = parent
    while ancestor is not None:  # prevent making a scenario its own ancestor
        if ancestor is row:
            raise InvalidInput("A scenario cannot be its own ancestor")
        ancestor = ancestor.parent
    row.parent = parent


def _write(db: Session, row: ScenarioRow, data: ScenarioIn) -> None:
    for kind, items in (("event", data.events), ("intervention", data.interventions)):
        ids = [i.id for i in items]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise InvalidInput(f"Duplicate {kind} ids: {', '.join(dupes)}")
    _set_parent(db, row, data.parent_id)
    row.name, row.description = data.name, data.description
    if data.seed is not None:
        row.seed = data.seed
    elif row.seed is None:
        row.seed = row.parent.seed if row.parent else DEFAULT_SEED
    row.remove_event_ids = list(data.remove_events)
    row.events.clear()
    row.interventions.clear()
    db.flush()
    for i, e in enumerate(data.events):
        row.events.append(ScenarioEventRow(
            key=e.id, type=e.type, target_key=e.target_id, start_time=e.start_time,
            duration=e.duration, severity=e.severity, probability=e.probability, position=i,
        ))
    for i, iv in enumerate(data.interventions):
        row.interventions.append(InterventionRow(
            key=iv.id, type=iv.type, params=iv.params, cost=iv.cost,
            description=iv.description, position=i,
        ))
    db.flush()
    check(row)


def create(db: Session, system_id: str, data: ScenarioIn) -> ScenarioRow:
    system = systems.get(db, system_id)
    row = ScenarioRow(system=system, name=data.name, seed=None)
    db.add(row)
    try:
        _write(db, row, data)
    except Exception:
        db.rollback()
        raise
    db.commit()
    return row


def update(db: Session, scenario_id: str, data: ScenarioIn) -> ScenarioRow:
    row = get(db, scenario_id)
    try:
        _write(db, row, data)
    except Exception:
        db.rollback()
        raise
    db.commit()
    return row


def branch(db: Session, scenario_id: str, name: str | None = None) -> ScenarioRow:
    """Create an empty child that inherits everything from this scenario."""
    parent = get(db, scenario_id)
    return create(db, parent.system_id, ScenarioIn(name=name or f"{parent.name} (branch)",
                                                     parent_id=parent.id))


def delete(db: Session, scenario_id: str) -> None:
    row = get(db, scenario_id)
    if row.children:
        raise Conflict(
            f"Scenario {row.name!r} has {len(row.children)} branch(es); delete them first"
        )
    db.delete(row)
    db.commit()
