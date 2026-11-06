"""Load an experiment (system + scenarios) from a JSON file or dict."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Event, System
from .simulation.branching import Intervention, Scenario


@dataclass
class Experiment:
    system: System
    scenarios: list[Scenario]
    until: float


def load_experiment(data: dict[str, Any]) -> Experiment:
    system = System.from_dict(data["system"])
    by_id: dict[str, Scenario] = {}
    scenarios: list[Scenario] = []
    for s in data.get("scenarios", []):
        parent_id = s.get("parent")
        if parent_id is not None and parent_id not in by_id:
            raise ValueError(f"Scenario {s['id']}: parent {parent_id!r} must be defined before it")
        scenario = Scenario(
            id=s["id"],
            name=s.get("name", s["id"]),
            events=[Event.from_dict(e) for e in s.get("events", [])],
            interventions=[Intervention.from_dict(i) for i in s.get("interventions", [])],
            parent=by_id.get(parent_id) if parent_id else None,
            remove_event_ids=list(s.get("remove_events", [])),
            seed=int(s.get("seed", by_id[parent_id].seed if parent_id else 42)),
        )
        by_id[scenario.id] = scenario
        scenarios.append(scenario)
    return Experiment(system=system, scenarios=scenarios, until=float(data.get("until", 30)))


def load_experiment_file(path: str | Path) -> Experiment:
    return load_experiment(json.loads(Path(path).read_text()))
