"""Pydantic models for the HTTP API.

Field names match the experiment JSON format (examples/ecommerce.json),
so the same shapes are used by the API, import/export and the frontend.
Pydantic checks shapes and types; the domain models (app.models) check
meaning, such as a dependency pointing at a component that does not exist.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Key = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.\-]+$")

InterventionType = Literal[
    "add_component", "remove_component", "add_dependency", "remove_dependency", "set_attribute",
    "set_dependency_attribute", "set_parameter",
]
# Event and relationship types depend on the domain, so they are plain strings
# here, checked against the domain registry (and per domain by the services).
MetricValue = float | int | None


def _known(kind: str, value: str) -> str:
    from .domains.registry import known_event_types, known_relationship_types

    known = known_event_types() if kind == "event" else known_relationship_types()
    if value not in known:
        raise ValueError(f"unknown {kind} type {value!r}; expected one of {sorted(known)}")
    return value


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
    dependency_type: str = "requires"
    group: str | None = None
    propagation_delay: float = Field(default=0.0, ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("dependency_type")
    @classmethod
    def _type_known(cls, v: str) -> str:
        return _known("relationship", v)


class SystemIn(_Model):
    name: str = Field(min_length=1, max_length=200)
    domain: str = "software_infrastructure"
    description: str = ""
    components: list[ComponentIn] = Field(default_factory=list)
    dependencies: list[DependencyIn] = Field(default_factory=list)
    # System-wide variables (e.g. arrival rate) that scenarios can change.
    parameters: dict[str, Any] = Field(default_factory=dict)


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
    type: str
    target_id: str
    start_time: float = Field(ge=0)
    duration: float | None = Field(default=None, gt=0)
    severity: float = 1.0
    probability: float = Field(default=1.0, ge=0, le=1)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _type_known(cls, v: str) -> str:
        return _known("event", v)


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


# Metric key -> value. Which keys exist depends on the domain; see
# GET /api/domains for their labels, units and whether lower is better.
Metrics = dict[str, MetricValue]


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
    domain: str = "software_infrastructure"
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
    # variable -> entity -> [(time, value)]; value None means no value (e.g. no latency while down)
    series: dict[str, dict[str, list[tuple[float, float | None]]]] = Field(default_factory=dict)
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


class MetricStatsOut(_Model):
    mean: float | None
    std: float | None
    min: float | None
    p5: float | None
    p50: float | None
    p95: float | None
    max: float | None
    missing: int = 0  # runs where the metric had no value


class RiskOut(_Model):
    metric: str
    mean: float | None
    p95: float | None  # the bad-case percentile (p5 for higher-is-better metrics)
    worst_5_percent_mean: float | None
    p_nonzero: float | None


class DriverOut(_Model):
    event_id: str
    frequency: float
    mean_if_occurred: float
    mean_if_not: float
    impact: float


class MonteCarloOut(_Model):
    id: str
    scenario_id: str
    scenario_name: str
    runs: int
    base_seed: int
    until: float
    # True when no event is probabilistic, so every run is identical.
    deterministic: bool
    # Infrastructure-specific summary (None for other domains).
    aggregates: MonteCarloAggregates | None
    downtimes: list[float]  # one per run, for the histogram (infrastructure)
    elapsed_ms: float
    created_at: datetime
    # Generic summary for every domain (empty for batches stored before Phase 3).
    domain: str = "software_infrastructure"
    risk_metric: str = "downtime"
    risk_values: list[MetricValue] = Field(default_factory=list)
    event_frequency: dict[str, float] = Field(default_factory=dict)  # event id -> share of runs it happened
    metric_stats: dict[str, MetricStatsOut] = Field(default_factory=dict)
    risk: RiskOut | None = None
    drivers: list[DriverOut] = Field(default_factory=list)


# ---- decisions --------------------------------------------------------
class ObjectiveIn(_Model):
    metric: str
    weight: float = Field(default=1.0, ge=0)
    direction: Literal["minimize", "maximize"] | None = None  # None: from the domain catalog


class ConstraintIn(_Model):
    metric: str
    op: Literal["<=", ">=", "<", ">"]
    value: float
    confidence: float | None = Field(default=None, gt=0, le=1)  # chance constraint (Monte Carlo)
    label: str = ""


class DecisionModelIn(_Model):
    objectives: list[ObjectiveIn] = Field(default_factory=list)
    constraints: list[ConstraintIn] = Field(default_factory=list)


class DecisionModelOut(DecisionModelIn):
    is_default: bool  # True when nothing has been saved and the domain's defaults are shown


class EvaluateRequest(_Model):
    scenario_ids: list[str] | None = None  # None: every scenario of the system
    until: float = Field(default=30.0, gt=0, le=1_000_000)
    # 1: one run per scenario with its own seed. More: Monte Carlo, scored on the mean.
    runs: int = Field(default=1, ge=1, le=5_000)
    base_seed: int | None = None
    baseline_id: str | None = None  # future to compare the recommendation with
    model: DecisionModelIn | None = None  # unsaved objectives to try; None: the saved ones


class ConstraintCheckOut(_Model):
    metric: str
    description: str
    value: MetricValue
    satisfied: bool
    satisfied_share: float | None


class ObjectiveScoreOut(_Model):
    metric: str
    value: MetricValue
    score: float
    weight: float
    contribution: float


class FutureOut(_Model):
    id: str  # scenario id
    name: str
    rank: int
    score: float  # 0..1, relative to the other futures in this evaluation
    feasible: bool
    pareto: bool
    dominated_by: list[str]
    values: dict[str, MetricValue]
    metrics: Metrics  # every metric (means when runs > 1)
    constraints: list[ConstraintCheckOut]
    objectives: list[ObjectiveScoreOut]
    stats: dict[str, MetricStatsOut] | None = None  # spread over runs (runs > 1)
    risk: RiskOut | None = None
    drivers: list[DriverOut] = Field(default_factory=list)


class InsightOut(_Model):
    kind: str
    text: str
    future_ids: list[str]
    metrics: list[str]


class EvaluationOut(_Model):
    system_id: str
    domain: str
    until: float
    runs: int
    model: DecisionModelIn
    futures: list[FutureOut]  # rank order
    skipped_objectives: list[str]  # objectives with no data in any future
    recommended: str | None
    robust: bool | None
    weight_flips: list[dict[str, Any]]
    baseline_id: str | None
    insights: list[InsightOut]
    elapsed_ms: float


class SensitivityRequest(_Model):
    until: float = Field(default=30.0, gt=0, le=1_000_000)
    metric: str | None = None  # None: the domain's risk metric
    delta: float = Field(default=0.2, gt=0, lt=1)
    runs: int = Field(default=1, ge=1, le=500)


class SensitivityRowOut(_Model):
    id: str
    kind: str
    target: str
    key: str
    value: float
    low_value: float
    high_value: float
    low: MetricValue
    high: MetricValue
    swing: float


class SensitivityOut(_Model):
    scenario_id: str
    metric: str
    baseline: MetricValue
    delta: float
    runs: int
    rows: list[SensitivityRowOut]
    elapsed_ms: float


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
    objectives: DecisionModelIn | None = None  # the decision model; omitted = domain defaults


class ImportOut(_Model):
    system_id: str
    # experiment-file scenario id -> database scenario id
    scenario_ids: dict[str, str]


# ---- domains ------------------------------------------------------------
class DomainOut(BaseModel):
    """A domain's catalog (see app/domains/spec.py). Read-only, so extra keys are fine."""

    name: str
    label: str
    description: str
    time_unit: str
    entity_types: list[dict[str, Any]]
    relationship_types: list[dict[str, Any]]
    event_types: list[dict[str, Any]]
    intervention_types: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    risk_metric: str
    assumptions: list[str]
    parameters: list[dict[str, Any]]
    default_objectives: list[tuple[str, float]] = Field(default_factory=list)
    open_entity_types: bool = False
    default_until: float = 30.0
    features: list[str] = Field(default_factory=list)
    edge_meaning: str = ""
