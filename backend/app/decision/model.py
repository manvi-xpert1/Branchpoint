"""What the decision maker cares about: objectives (with weights) and constraints.

An **objective** is a metric to improve. Its direction comes from the
domain catalog (``better="lower"`` means minimise) unless overridden, and
its weight says how much it matters relative to the others.

A **constraint** is a hard limit, e.g. ``availability >= 0.99``. A future
that breaks a constraint is *infeasible*: it is still shown, but ranked
after every feasible one. With Monte Carlo samples a constraint can be a
*chance constraint*: ``confidence=0.95`` means it must hold in at least
95% of runs.

Pure data classes with validation against a ``DomainSpec``; no I/O.
"""

from __future__ import annotations

import operator
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from ..domains.spec import DomainSpec

Direction = Literal["minimize", "maximize"]
Op = Literal["<=", ">=", "<", ">"]

OPS = {"<=": operator.le, ">=": operator.ge, "<": operator.lt, ">": operator.gt}


@dataclass
class Objective:
    metric: str
    weight: float = 1.0
    direction: Direction | None = None  # None: use the metric's "better" from the catalog

    def resolved_direction(self, spec: DomainSpec) -> Direction:
        if self.direction:
            return self.direction
        return "maximize" if spec.metric(self.metric).better == "higher" else "minimize"


@dataclass
class Constraint:
    metric: str
    op: Op
    value: float
    confidence: float | None = None  # chance constraint: share of runs that must satisfy it
    label: str = ""

    def holds(self, value: float | None) -> bool:
        """A missing value (e.g. "never recovered") never satisfies a constraint."""
        return value is not None and OPS[self.op](value, self.value)

    def describe(self, spec: DomainSpec) -> str:
        from ..domains.spec import format_value

        m = spec.metric(self.metric)
        text = f"{m.label} {self.op} {format_value(m, self.value)}"
        if self.confidence is not None:
            text += f" in {self.confidence:.0%} of runs"
        return self.label or text


@dataclass
class DecisionModel:
    objectives: list[Objective] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)

    def errors(self, spec: DomainSpec) -> list[str]:
        known = {m.key for m in spec.metrics}
        problems = []
        for o in self.objectives:
            if o.metric not in known:
                problems.append(f"objective: unknown metric {o.metric!r}")
            if o.weight < 0:
                problems.append(f"objective {o.metric}: weight must be 0 or more")
        if self.objectives and not any(o.weight > 0 for o in self.objectives):
            problems.append("at least one objective needs a weight above 0")
        for c in self.constraints:
            if c.metric not in known:
                problems.append(f"constraint: unknown metric {c.metric!r}")
            if c.op not in OPS:
                problems.append(f"constraint {c.metric}: unknown operator {c.op!r}")
            if c.confidence is not None and not 0 < c.confidence <= 1:
                problems.append(f"constraint {c.metric}: confidence must be in (0, 1]")
        if len({o.metric for o in self.objectives}) != len(self.objectives):
            problems.append("each metric can be an objective only once")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DecisionModel":
        data = data or {}
        return cls(
            objectives=[Objective(**o) for o in data.get("objectives", [])],
            constraints=[Constraint(**c) for c in data.get("constraints", [])],
        )


def default_model(spec: DomainSpec) -> DecisionModel:
    """The domain's suggested objectives, or every metric that has a direction."""
    if spec.default_objectives:
        objectives = [Objective(k, w) for k, w in spec.default_objectives]
    else:
        objectives = [Objective(m.key, 1.0) for m in spec.metrics if m.better != "neutral"]
    return DecisionModel(objectives=objectives)
