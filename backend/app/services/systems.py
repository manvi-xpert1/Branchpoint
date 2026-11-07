"""System CRUD and conversion between database rows and the domain model."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import ComponentRow, DependencyRow, ScenarioRow, SystemRow
from ..domains.registry import get_domain
from ..models import System, ValidationError
from ..schemas import (
    ComponentIn,
    DependencyIn,
    SystemAnalysis,
    SystemIn,
    SystemOut,
    SystemSummary,
)
from ..simulation.graph import DependencyGraph
from .errors import InvalidInput, NotFound


# ---- conversion -------------------------------------------------------
def definition_dict(data: SystemIn, system_id: str = "draft") -> dict:
    """SystemIn -> the plain dict format the domain model understands."""
    return {
        "id": system_id,
        "name": data.name,
        "domain": data.domain,
        "description": data.description,
        "parameters": data.parameters,
        "components": [
            {
                "id": c.id,
                "name": c.name or c.id,
                "type": c.type,
                "entry_point": c.entry_point,
                "attributes": c.attributes,
            }
            for c in data.components
        ],
        "dependencies": [
            {**d.model_dump(), "id": d.id or f"{d.source_id}->{d.target_id}"} for d in data.dependencies
        ],
    }


def to_domain_from_input(data: SystemIn, system_id: str = "draft") -> System:
    """Build and validate a domain System. Raises InvalidInput."""
    try:
        domain = get_domain(data.domain)
        system = System.from_dict(definition_dict(data, system_id))
    except (ValidationError, ValueError) as exc:
        raise InvalidInput(str(exc)) from exc
    problems = domain.errors(system)
    if problems:
        raise InvalidInput("; ".join(problems))
    return system


def to_input(row: SystemRow) -> SystemIn:
    return SystemIn(
        name=row.name,
        domain=row.domain,
        description=row.description,
        parameters=row.parameters or {},
        components=[
            ComponentIn(
                id=c.key, name=c.name, type=c.type, entry_point=c.entry_point,
                attributes=c.attributes or {}, layout=c.layout,
            )
            for c in row.components
        ],
        dependencies=[
            DependencyIn(
                id=d.key, source_id=d.source_key, target_id=d.target_key,
                dependency_type=d.dependency_type, group=d.group,
                propagation_delay=d.propagation_delay, attributes=d.attributes or {},
            )
            for d in row.dependencies
        ],
    )


def to_domain(row: SystemRow) -> System:
    return to_domain_from_input(to_input(row), row.id)


def to_schema(row: SystemRow) -> SystemOut:
    return SystemOut(id=row.id, created_at=row.created_at, updated_at=row.updated_at,
                     **to_input(row).model_dump())


# ---- queries ----------------------------------------------------------
def get(db: Session, system_id: str) -> SystemRow:
    row = db.get(SystemRow, system_id)
    if row is None:
        raise NotFound(f"System {system_id!r} not found")
    return row


def list_summaries(db: Session) -> list[SystemSummary]:
    scenario_counts = dict(
        db.execute(select(ScenarioRow.system_id, func.count()).group_by(ScenarioRow.system_id)).all()
    )
    rows = db.scalars(select(SystemRow).order_by(SystemRow.updated_at.desc())).all()
    return [
        SystemSummary(
            id=r.id, name=r.name, domain=r.domain, description=r.description,
            component_count=len(r.components), dependency_count=len(r.dependencies),
            scenario_count=scenario_counts.get(r.id, 0), updated_at=r.updated_at,
        )
        for r in rows
    ]


# ---- commands ---------------------------------------------------------
def _write_definition(db: Session, row: SystemRow, data: SystemIn) -> None:
    to_domain_from_input(data)  # validate before touching the database
    row.name, row.domain, row.description = data.name, data.domain, data.description
    row.parameters = data.parameters
    # Delete old graph rows before inserting new ones so (system_id, key)
    # stays unique even when a key is reused.
    row.components.clear()
    row.dependencies.clear()
    db.flush()
    for i, c in enumerate(data.components):
        row.components.append(ComponentRow(
            key=c.id, name=c.name or c.id, type=c.type, entry_point=c.entry_point,
            attributes=c.attributes, layout=c.layout, position=i,
        ))
    for i, d in enumerate(data.dependencies):
        row.dependencies.append(DependencyRow(
            key=d.id or f"{d.source_id}->{d.target_id}", source_key=d.source_id,
            target_key=d.target_id, dependency_type=d.dependency_type, group=d.group,
            propagation_delay=d.propagation_delay, attributes=d.attributes, position=i,
        ))


def create(db: Session, data: SystemIn) -> SystemRow:
    row = SystemRow(name=data.name)
    db.add(row)
    _write_definition(db, row, data)
    db.commit()
    return row


def update(db: Session, system_id: str, data: SystemIn) -> SystemRow:
    from . import scenarios  # local import: scenarios imports this module

    row = get(db, system_id)
    _write_definition(db, row, data)
    db.flush()
    db.expire(row, ["components", "dependencies"])
    # Editing the system may break existing scenarios (e.g. an event now
    # targets a deleted component). Refuse the edit rather than leave
    # scenarios that cannot run.
    try:
        for scenario in row.scenarios:
            scenarios.check(scenario)
    except InvalidInput as exc:
        db.rollback()
        raise InvalidInput(f"This change would break a scenario: {exc.message}") from exc
    db.commit()
    return row


def delete(db: Session, system_id: str) -> None:
    row = get(db, system_id)
    # Delete branches leaf-first, because a parent scenario cannot be
    # removed while children reference it.
    remaining = list(row.scenarios)
    while remaining:
        parent_ids = {s.parent_id for s in remaining}
        leaves = [s for s in remaining if s.id not in parent_ids]
        for s in leaves:
            db.delete(s)
        db.flush()
        remaining = [s for s in remaining if s not in leaves]
    db.expire(row, ["scenarios"])
    db.delete(row)
    db.commit()


def analyze(data: SystemIn) -> SystemAnalysis:
    """Validate a definition and report structure, without saving it."""
    try:
        system = to_domain_from_input(data)
    except InvalidInput as exc:
        return SystemAnalysis(valid=False, errors=exc.message.splitlines()[1:] or exc.message.split("; "),
                              warnings=[], cycle=None, topological_order=None,
                              entry_points=[], blast_radius={})
    graph = DependencyGraph(system)
    cycle = graph.find_cycle()
    domain = get_domain(system.domain)
    features = set(domain.spec.features)
    warnings = domain.validate(system)
    if cycle and "propagation_delay" in features:  # loops are normal in flow domains (e.g. ICU -> ward)
        warnings.append("Dependency cycle: " + " -> ".join(cycle)
                        + ". Components in a hard cycle cannot recover once both fail.")
    entry = [c.id for c in system.components.values() if c.entry_point]
    if system.components and not entry and "entry_points" in features:
        warnings.append("No entry points marked; availability will be measured across all components.")
    return SystemAnalysis(
        valid=True,
        errors=[],
        warnings=warnings,
        cycle=cycle,
        topological_order=None if cycle else graph.topological_order(),
        entry_points=entry,
        blast_radius={
            cid: sorted(k for k in graph.impact_bfs(cid) if k != cid) for cid in system.components
        },
    )
