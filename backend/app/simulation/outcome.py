"""What one simulation run produces, in a domain-independent shape."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .state import LogEntry


class MetricValues(dict):
    """Metric key -> value (a float, an int or None).

    It is a plain dict, so any domain can report any metrics. Attribute
    access (``metrics.downtime``) also works, which keeps engine code and
    tests readable.
    """

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key) from None

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


@dataclass
class Outcome:
    metrics: MetricValues
    # Causal log: every entry can point at the entry that caused it.
    log: list[LogEntry]
    # Status over time per entity: entity -> [(time, status), ...]. Optional.
    timelines: dict[str, list[tuple[float, Any]]] = field(default_factory=dict)
    # Numbers over time: variable -> entity -> [(time, value), ...].
    # E.g. {"queue": {"ward": [...]}, "inventory": {"warehouse": [...]}}.
    series: dict[str, dict[str, list[tuple[float, float]]]] = field(default_factory=dict)
    skipped_events: list[str] = field(default_factory=list)
    # Domain-specific final state, for callers that need more detail.
    state: Any = None
