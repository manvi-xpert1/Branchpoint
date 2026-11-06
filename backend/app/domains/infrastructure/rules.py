"""Propagation rules for software infrastructure.

Rules in plain English:

* A failure event makes a component FAILED.
* A latency event makes it DEGRADED.
* A traffic spike multiplies its load. Above capacity it is DEGRADED;
  above ``capacity * overload_failure_ratio`` (default 1.5) it is FAILED.
* Dependencies are grouped. A dependency with no ``group`` is its own
  group. Within a group the component only needs ONE member to be up,
  which is how replicas and fallbacks work.
  - A ``fallback`` member can stand in, but only in DEGRADED mode.
  - A group made only of ``optional`` members can at worst DEGRADE the
    component.
* The effective status is the worst of the component's own status and
  every group's impact.
"""

from __future__ import annotations

from collections import defaultdict

from ...models import Component, Dependency, Status
from ...simulation.state import Effect
from ..base import DomainRules, Verdict


class InfrastructureRules(DomainRules):
    name = "software_infrastructure"

    def intrinsic_status(self, component: Component, effects: list[Effect]) -> Verdict:
        worst = Verdict(Status.HEALTHY, "operating normally")
        multiplier = 1.0
        for effect in effects:
            if effect.type == "component_failure":
                return Verdict(Status.FAILED, f"failed ({effect.event_id})")
            if effect.type == "latency_increase" and worst.status < Status.DEGRADED:
                worst = Verdict(Status.DEGRADED, f"high latency ({effect.event_id})")
            if effect.type == "traffic_spike":
                multiplier *= effect.severity

        if multiplier != 1.0:
            attrs = component.attributes
            capacity = attrs.get("capacity")
            if capacity:
                load = attrs.get("current_load", 0) * multiplier
                ratio = attrs.get("overload_failure_ratio", 1.5)
                if load > capacity * ratio:
                    return Verdict(Status.FAILED, f"overloaded: load {load:g} > {capacity * ratio:g}")
                if load > capacity and worst.status < Status.DEGRADED:
                    worst = Verdict(Status.DEGRADED, f"over capacity: load {load:g} > {capacity:g}")
        return worst

    def effective_status(
        self,
        component: Component,
        intrinsic: Verdict,
        dependencies: list[tuple[Dependency, Status]],
    ) -> Verdict:
        groups: dict[str, list[tuple[Dependency, Status]]] = defaultdict(list)
        for dep, target_status in dependencies:
            groups[dep.group or dep.id].append((dep, target_status))

        result = intrinsic
        for name, members in groups.items():
            # Best available member (min = best since higher is worse).
            available = min(
                max(st, Status.DEGRADED) if dep.dependency_type == "fallback" else st
                for dep, st in members
            )
            only_optional = all(dep.dependency_type == "optional" for dep, _ in members)
            impact = min(available, Status.DEGRADED) if only_optional else available

            if impact > result.status:
                result = Verdict(impact, self._explain(members, impact))
        return result

    @staticmethod
    def _explain(members: list[tuple[Dependency, Status]], impact: Status) -> str:
        targets = ", ".join(f"{dep.target_id} is {st}" for dep, st in members)
        if impact == Status.DEGRADED and any(
            dep.dependency_type == "fallback" and st != Status.FAILED for dep, st in members
        ):
            return f"running on fallback ({targets})"
        return f"dependency problem ({targets})"
