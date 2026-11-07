"""One-at-a-time sensitivity analysis ("tornado" data).

Question answered: *which inputs move this outcome the most?*

For each numeric input (a component attribute, a system parameter, or an
event's probability, duration or severity) we run the scenario twice:
once with the input lowered by ``delta`` (default 20%) and once raised by
it, keeping everything else (including the seeds) the same. The swing,
the difference between the two results, ranks the inputs. Because the
seeds are the same, the difference comes from the input, not from luck
(common random numbers).

With ``runs > 1`` each point is the mean of a Monte Carlo batch, which
makes sense when the scenario has probabilistic events.

Inputs that interventions add or override are perturbed *before* the
interventions apply, so an input that an intervention overrides shows no
effect, which is the truth for that scenario.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..models import System
from ..simulation.branching import Scenario, run_scenario
from ..simulation.montecarlo import run_monte_carlo

SKIP_ATTRIBUTES = {"layout"}
EVENT_FIELDS = ("probability", "duration", "severity")


@dataclass
class Input:
    kind: str  # "attribute", "parameter" or "event"
    target: str  # component id, "system" or event id
    key: str
    value: float

    @property
    def id(self) -> str:
        return f"{self.kind}:{self.target}:{self.key}"


@dataclass
class SensitivityRow:
    input: Input
    low_value: float
    high_value: float
    low: float | None
    high: float | None
    swing: float  # |high - low| (0 if either is missing)


@dataclass
class SensitivityResult:
    metric: str
    baseline: float | None
    delta: float
    runs: int
    rows: list[SensitivityRow]  # largest swing first


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def find_inputs(system: System, scenario: Scenario) -> list[Input]:
    inputs: list[Input] = []
    for c in system.components.values():
        for key, value in c.attributes.items():
            if key not in SKIP_ATTRIBUTES and (v := _number(value)) is not None and v != 0:
                inputs.append(Input("attribute", c.id, key, v))
    for key, value in system.parameters.items():
        if (v := _number(value)) is not None and v != 0:
            inputs.append(Input("parameter", "system", key, v))
    for e in scenario.resolved_events():
        for key in EVENT_FIELDS:
            v = _number(getattr(e, key))
            if v is None or v == 0:
                continue
            if key == "severity" and e.type != "traffic_spike":
                continue  # severity only means something for spikes in this domain
            inputs.append(Input("event", e.id, key, v))
    return inputs


def _with_input(system: System, scenario: Scenario, inp: Input, value: float) -> tuple[System, Scenario]:
    sys = system.copy()
    events = scenario.resolved_events()
    if inp.kind == "attribute":
        sys.components[inp.target].attributes[inp.key] = value
    elif inp.kind == "parameter":
        sys.parameters[inp.key] = value
    else:
        if inp.key == "probability":
            value = min(1.0, max(0.0, value))
        events = [replace(e, **{inp.key: value}) if e.id == inp.target else e for e in events]
    flat = Scenario(scenario.id, scenario.name, events=events,
                    interventions=scenario.resolved_interventions(), seed=scenario.seed)
    return sys, flat


def _measure(system: System, scenario: Scenario, until: float, metric: str, runs: int) -> float | None:
    if runs <= 1:
        return run_scenario(system, scenario, until).metrics.get(metric)
    stats = run_monte_carlo(system, scenario, until, runs).metric_stats or {}
    return stats[metric].mean if metric in stats else None


def sensitivity(system: System, scenario: Scenario, until: float, metric: str,
                delta: float = 0.2, runs: int = 1, max_inputs: int = 60) -> SensitivityResult:
    if not 0 < delta < 1:
        raise ValueError("delta must be between 0 and 1")
    inputs = find_inputs(system, scenario)[:max_inputs]
    baseline = _measure(system, scenario, until, metric, runs)
    rows = []
    for inp in inputs:
        lo_v, hi_v = inp.value * (1 - delta), inp.value * (1 + delta)
        if inp.key == "probability":
            lo_v, hi_v = max(0.0, lo_v), min(1.0, hi_v)
        low = _measure(*_with_input(system, scenario, inp, lo_v), until, metric, runs)
        high = _measure(*_with_input(system, scenario, inp, hi_v), until, metric, runs)
        swing = abs(high - low) if low is not None and high is not None else 0.0
        rows.append(SensitivityRow(inp, lo_v, hi_v, low, high, swing))
    rows.sort(key=lambda r: (-r.swing, r.input.id))
    return SensitivityResult(metric, baseline, delta, runs, rows)


__all__ = ["Input", "SensitivityRow", "SensitivityResult", "find_inputs", "sensitivity"]
