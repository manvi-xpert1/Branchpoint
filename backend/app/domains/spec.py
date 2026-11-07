"""Domain catalogs: a machine-readable description of what a domain offers.

A ``DomainSpec`` lists the building blocks of a domain (entity types and
their attributes, relationship types, events, decisions), the metrics a run
produces with their units and whether lower or higher is better, and the
assumptions the model makes. The API serves it at ``GET /api/domains`` so
the frontend can build its palette, inspector forms, event forms and
comparison columns without hard-coding any one domain.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

FieldKind = Literal["number", "integer", "probability", "text", "boolean", "choice"]
Better = Literal["lower", "higher", "neutral"]
MetricFormat = Literal["number", "percent", "duration", "count", "money"]


@dataclass(frozen=True)
class FieldSpec:
    """One editable value: an attribute, an event setting or a parameter."""

    key: str
    label: str
    kind: FieldKind = "number"
    unit: str = ""
    default: Any = None
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] = ()
    help: str = ""


@dataclass(frozen=True)
class EntityType:
    type: str
    label: str
    short: str  # two-letter badge shown on the graph
    color: str  # badge colour on the dark graph stage
    fields: tuple[FieldSpec, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class RelationshipType:
    type: str
    label: str
    description: str = ""
    style: Literal["solid", "dashed", "dotted"] = "solid"
    fields: tuple[FieldSpec, ...] = ()


@dataclass(frozen=True)
class EventType:
    type: str
    label: str
    description: str = ""
    target: Literal["entity", "relationship"] = "entity"
    # Label of the generic ``severity`` number for this event, or None if unused.
    severity_label: str | None = None
    uses_duration: bool = True
    fields: tuple[FieldSpec, ...] = ()  # extra settings stored in Event.params


@dataclass(frozen=True)
class InterventionType:
    type: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    better: Better
    unit: str = ""
    format: MetricFormat = "number"
    description: str = ""


@dataclass(frozen=True)
class DomainSpec:
    name: str
    label: str
    description: str
    time_unit: str
    entity_types: tuple[EntityType, ...]
    relationship_types: tuple[RelationshipType, ...]
    event_types: tuple[EventType, ...]
    intervention_types: tuple[InterventionType, ...]
    metrics: tuple[MetricDef, ...]
    # The metric Monte Carlo treats as "how bad did it go" (e.g. downtime).
    risk_metric: str
    assumptions: tuple[str, ...] = ()
    parameters: tuple[FieldSpec, ...] = field(default=())  # system-wide variables
    # Starting objectives for the decision layer: (metric key, weight). Users can change them.
    default_objectives: tuple[tuple[str, float], ...] = ()
    # False: components must use one of entity_types (checked by Domain.errors).
    open_entity_types: bool = False
    # UI features this domain uses: "entry_points", "groups", "propagation_delay" (status propagation),
    # "presets" (replica/fallback shortcuts). Flow domains (hospital, cold chain) use none.
    features: tuple[str, ...] = ()
    # How to read an arrow in the editor.
    edge_meaning: str = "The arrow points from a component to what it depends on."
    # Suggested simulated window for new runs, in time_unit.
    default_until: float = 30.0

    def metric(self, key: str) -> MetricDef:
        for m in self.metrics:
            if m.key == key:
                return m
        raise KeyError(f"{self.name} has no metric {key!r}")

    @property
    def relationship_type_names(self) -> set[str]:
        return {r.type for r in self.relationship_types}

    @property
    def event_type_names(self) -> set[str]:
        return {e.type for e in self.event_types}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def format_value(metric: MetricDef, value: Any) -> str:
    """Human-readable value for tables and the CLI."""
    if value is None:
        return "-"
    if metric.format == "percent":
        return f"{value:.1%}"
    if metric.format == "money" or (isinstance(value, float) and abs(value) >= 10_000):
        if isinstance(value, float) and not value.is_integer() and abs(value) < 1000:
            return f"{value:,.2f}"
        return f"{value:,.0f}"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)
