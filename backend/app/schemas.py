"""Pydantic models for the HTTP API.

Field names match the experiment JSON format (examples/ecommerce.json),
so the same shapes are used by the API, import/export and the frontend.
Pydantic checks shapes and types; the domain models (app.models) check
meaning, such as a dependency pointing at a component that does not exist.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Key = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.\-]+$")

EventType = Literal["component_failure", "component_recovery", "traffic_spike", "latency_increase"]
DependencyType = Literal["requires", "optional", "fallback"]
InterventionType = Literal[
    "add_component", "remove_component", "add_dependency", "remove_dependency", "set_attribute"
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- systems ----------------------------------------------------------
class ComponentIn(_Model):
    id: str = Key
    name: str | None = None
    type: str = "service"
    entry_point: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)
    layout: dict[str, Any] | None = None  # {"x": .., "y": ..} from the visual editor


class DependencyIn(_Model):
    id: str | None = Field(default=None, max_length=200)
    source_id: str
    target_id: str
    dependency_type: DependencyType = "requires"
    group: str | None = None
    propagation_delay: float = Field(default=0.0, ge=0)


class SystemIn(_Model):
    name: str = Field(min_length=1, max_length=200)
    domain: str = "software_infrastructure"
    description: str = ""
    components: list[ComponentIn] = Field(default_factory=list)
    dependencies: list[DependencyIn] = Field(default_factory=list)


class SystemOut(SystemIn):
    id: str
    created_at: datetime
    updated_at: datetime


class SystemSummary(_Model):
    id: str
    name: str
    domain: str
    description: str
    component_count: int
    dependency_count: int
    scenario_count: int
    updated_at: datetime


class SystemAnalysis(_Model):
    valid: bool
    errors: list[str]
    warnings: list[str]
    cycle: list[str] | None
    topological_order: list[str] | None
    entry_points: list[str]
    # component -> components that could be affected if it fails
    blast_radius: dict[str, list[str]]


# ---- scenarios --------------------------------------------------------
class EventIn(_Model):
    id: str = Key
    type: EventType
    target_id: str
    start_time: float = Field(ge=0)
    duration: float | None = Field(default=None, gt=0)
    severity: float = 1.0
    probability: float = Field(default=1.0, ge=0, le=1)


class InterventionIn(_Model):
    id: str = Key
    type: InterventionType
    params: dict[str, Any] = Field(default_factory=dict)
    cost: float = 0.0
    description: str = ""


class ScenarioIn(_Model):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    parent_id: str | None = None
    seed: int | None = None  # None: inherit the parent's seed (or 42)
    events: list[EventIn] = Field(default_factory=list)
    interventions: list[InterventionIn] = Field(default_factory=list)
    remove_events: list[str] = Field(default_factory=list)


class ScenarioOut(_Model):
    id: str
    system_id: str
    parent_id: str | None
    name: str
    description: str
    seed: int
    events: list[EventIn]
    interventions: list[InterventionIn]
    remove_events: list[str]
    children: list[str]
    lineage: list[str]
    # What will actually run, after inheritance from ancestors.
    resolved_events: list[EventIn]
    resolved_interventions: list[InterventionIn]
    created_at: datetime
    updated_at: datetime


# ---- runs -------------------------------------------------------------
class RunRequest(_Model):
    until: float = Field(default=30.0, gt=0, le=1_000_000)


class Metrics(_Model):
    duration: float
    availability: float
    downtime: float
    degraded_time: float
    affected_components: int
    recovery_time: float | None
    cost: float


class LogEntryOut(_Model):
    seq: int
    time: float
    kind: str
    component_id: str
    message: str
    cause_seq: int | None
    event_id: str | None
    old_status: str | None
    new_status: str | None


class RunSummary(_Model):
    id: str
    scenario_id: str
    scenario_name: str
    status: str
    seed: int
    until: float
    metrics: Metrics
    elapsed_ms: float
    created_at: datetime


class RunOut(RunSummary):
    # The system as simulated: base snapshot with interventions applied.
    system: dict[str, Any]
    skipped_events: list[str]
    # component -> [[time, status], ...] for drawing the timeline / graph playback
    timelines: dict[str, list[tuple[float, str]]]
    log: list[LogEntryOut]


class ReplayOut(_Model):
    run_id: str
    identical: bool
    differences: list[str]


class CompareRequest(_Model):
    """Either compare existing runs, or run these scenarios now and compare."""

    run_ids: list[str] | None = None
    scenario_ids: list[str] | None = None
    until: float = Field(default=30.0, gt=0, le=1_000_000)

    @model_validator(mode="after")
    def _exactly_one(self) -> "CompareRequest":
        if bool(self.run_ids) == bool(self.scenario_ids):
            raise ValueError("Provide exactly one of run_ids or scenario_ids (non-empty)")
        return self


class CompareOut(_Model):
    runs: list[RunSummary]
    # metric -> run id with the best value (lowest downtime, highest availability...)
    best: dict[str, list[str]]


# ---- Monte Carlo ------------------------------------------------------
class MonteCarloRequest(_Model):
    runs: int = Field(default=1000, ge=1, le=10_000)
    until: float = Field(default=30.0, gt=0, le=1_000_000)
    base_seed: int | None = None  # None: use the scenario's seed


class MonteCarloAggregates(_Model):
    downtime_mean: float
    downtime_p50: float
    downtime_p95: float
    downtime_max: float
    p_any_downtime: float
    availability_mean: float
    degraded_time_mean: float
    event_frequency: dict[str, float]


class MonteCarloOut(_Model):
    id: str
    scenario_id: str
    scenario_name: str
    runs: int
    base_seed: int
    until: float
    # True when no event is probabilistic, so every run is identical.
    deterministic: bool
    aggregates: MonteCarloAggregates
    downtimes: list[float]  # one per run, for the histogram
    elapsed_ms: float
    created_at: datetime


# ---- experiments ------------------------------------------------------
class ExperimentScenarioIn(ScenarioIn):
    """Scenario in an experiment file: ids are local, parents reference them."""

    id: str = Key
    parent: str | None = None


class ExperimentSystemIn(SystemIn):
    id: str | None = None  # ignored on import; the database assigns ids


class ExperimentIn(_Model):
    until: float = Field(default=30.0, gt=0)
    system: ExperimentSystemIn
    scenarios: list[ExperimentScenarioIn] = Field(default_factory=list)


class ImportOut(_Model):
    system_id: str
    # experiment-file scenario id -> database scenario id
    scenario_ids: dict[str, str]
