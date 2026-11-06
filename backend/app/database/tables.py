"""SQLAlchemy table definitions.

Relational columns hold ids, ownership, relationships and anything we
filter on. Flexible, domain-specific data (component attributes,
intervention params, metrics) goes in JSON columns (JSONB on PostgreSQL).

User-facing ids such as "postgres" are stored as ``key`` and are unique
within their parent; every row also has its own surrogate primary key.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SystemRow(Base):
    __tablename__ = "systems"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(64), default="software_infrastructure")
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    components: Mapped[list[ComponentRow]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="ComponentRow.position"
    )
    dependencies: Mapped[list[DependencyRow]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="DependencyRow.position"
    )
    scenarios: Mapped[list[ScenarioRow]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="ScenarioRow.created_at"
    )


class ComponentRow(Base):
    __tablename__ = "components"
    __table_args__ = (UniqueConstraint("system_id", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    system_id: Mapped[str] = mapped_column(ForeignKey("systems.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(64))
    entry_point: Mapped[bool] = mapped_column(default=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # Canvas position from the visual editor (Week 7); optional.
    layout: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    system: Mapped[SystemRow] = relationship(back_populates="components")


class DependencyRow(Base):
    __tablename__ = "dependencies"
    __table_args__ = (UniqueConstraint("system_id", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    system_id: Mapped[str] = mapped_column(ForeignKey("systems.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(200))
    source_key: Mapped[str] = mapped_column(String(100))
    target_key: Mapped[str] = mapped_column(String(100))
    dependency_type: Mapped[str] = mapped_column(String(32), default="requires")
    group: Mapped[str | None] = mapped_column(String(100), nullable=True)
    propagation_delay: Mapped[float] = mapped_column(Float, default=0.0)
    position: Mapped[int] = mapped_column(Integer, default=0)

    system: Mapped[SystemRow] = relationship(back_populates="dependencies")


class ScenarioRow(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    system_id: Mapped[str] = mapped_column(ForeignKey("systems.id", ondelete="CASCADE"), index=True)
    # RESTRICT: a parent cannot be deleted while it has branches.
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("scenarios.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    seed: Mapped[int] = mapped_column(Integer, default=42)
    remove_event_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    system: Mapped[SystemRow] = relationship(back_populates="scenarios")
    parent: Mapped[ScenarioRow | None] = relationship(remote_side="ScenarioRow.id", back_populates="children")
    children: Mapped[list[ScenarioRow]] = relationship(back_populates="parent")
    events: Mapped[list[ScenarioEventRow]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan", order_by="ScenarioEventRow.position"
    )
    interventions: Mapped[list[InterventionRow]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan", order_by="InterventionRow.position"
    )
    runs: Mapped[list[SimulationRunRow]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan", order_by="SimulationRunRow.created_at"
    )
    monte_carlo_runs: Mapped[list[MonteCarloRunRow]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan", order_by="MonteCarloRunRow.created_at"
    )


class ScenarioEventRow(Base):
    __tablename__ = "scenario_events"
    __table_args__ = (UniqueConstraint("scenario_id", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(64))
    target_key: Mapped[str] = mapped_column(String(100))
    start_time: Mapped[float] = mapped_column(Float)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[float] = mapped_column(Float, default=1.0)
    probability: Mapped[float] = mapped_column(Float, default=1.0)
    position: Mapped[int] = mapped_column(Integer, default=0)

    scenario: Mapped[ScenarioRow] = relationship(back_populates="events")


class InterventionRow(Base):
    __tablename__ = "interventions"
    __table_args__ = (UniqueConstraint("scenario_id", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)

    scenario: Mapped[ScenarioRow] = relationship(back_populates="interventions")


class SimulationRunRow(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    seed: Mapped[int] = mapped_column(Integer)
    until: Mapped[float] = mapped_column(Float)
    # Exactly what was simulated, so the run can be replayed even after
    # the system or scenario has been edited.
    system_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType)
    scenario_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType)
    skipped_events: Mapped[list[str]] = mapped_column(JSONType, default=list)
    # component -> [[time, status], ...], used for playback in the UI
    timelines: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    elapsed_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scenario: Mapped[ScenarioRow] = relationship(back_populates="runs")
    log: Mapped[list[SimulationEventRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="SimulationEventRow.seq"
    )


class SimulationEventRow(Base):
    """One entry of a run's chronological, causally linked event log."""

    __tablename__ = "simulation_events"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # the engine's log entry id
    time: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(32))
    component_key: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    cause_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    old_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(16), nullable=True)

    run: Mapped[SimulationRunRow] = relationship(back_populates="log")


class MonteCarloRunRow(Base):
    """A batch of N seeded runs of one scenario, stored as a summary.

    1,000 full event logs would be large and rarely looked at, so only the
    aggregates and each run's downtime (for the histogram) are kept. Any
    single run can be reproduced by running the scenario with seed
    ``base_seed + i``.
    """

    __tablename__ = "monte_carlo_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True)
    runs: Mapped[int] = mapped_column(Integer)
    base_seed: Mapped[int] = mapped_column(Integer)
    until: Mapped[float] = mapped_column(Float)
    # Output of MonteCarloResult.to_dict(): aggregates + per-run downtimes.
    summary: Mapped[dict[str, Any]] = mapped_column(JSONType)
    # Resolved events and interventions, so the batch can be re-run later.
    scenario_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType)
    elapsed_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scenario: Mapped[ScenarioRow] = relationship(back_populates="monte_carlo_runs")
