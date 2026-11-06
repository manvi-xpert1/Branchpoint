"""Command-line runner.

    cd backend
    python -m app.cli ../examples/ecommerce.json
    python -m app.cli ../examples/ecommerce.json --timeline db-down
    python -m app.cli ../examples/ecommerce.json --explain db-down:api_gateway
    python -m app.cli ../examples/ecommerce.json --json results.json
    python -m app.cli ../examples/ecommerce.json --montecarlo 1000
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import load_experiment_file
from .models import Status
from .simulation.branching import SimulationResult, comparison_table, run_scenario
from .simulation.engine import explain
from .simulation.graph import DependencyGraph
from .simulation.montecarlo import MonteCarloResult, run_monte_carlo


def print_timeline(result: SimulationResult) -> None:
    print(f"\nTimeline: {result.scenario_name} (seed {result.seed})")
    for entry in result.log:
        marker = "*" if entry.kind == "event" else " "
        print(f"  t={entry.time:>5g} {marker} {entry.component_id:<16} {entry.message}")
    if result.skipped_events:
        print(f"  (probabilistic events that did not occur: {', '.join(result.skipped_events)})")


def print_explanation(result: SimulationResult, component_id: str) -> None:
    print(f"\nWhy did {component_id} change in '{result.scenario_name}'?")
    entries = [e for e in result.log if e.kind == "status_change" and e.component_id == component_id]
    if not entries:
        print("  It never changed status.")
        return
    worst = max(entries, key=lambda e: (e.new_status or Status.HEALTHY))
    for depth, entry in enumerate(explain(result.log, worst.id)):
        print(f"  {'  ' * depth}t={entry.time:g}  {entry.component_id}: {entry.message}")


def print_monte_carlo(results: list[MonteCarloResult]) -> None:
    runs = results[0].runs
    print(f"\nMonte Carlo: {runs} runs per scenario (model estimates, not predictions)\n")
    headers = ["Scenario", "Mean down", "p50", "p95", "Max", "P(down>0)", "Mean avail."]
    rows = []
    for r in results:
        a = r.aggregates
        name = r.scenario_name + ("" if not r.deterministic else " (deterministic)")
        rows.append([name, f"{a.downtime_mean:.2f}", f"{a.downtime_p50:g}", f"{a.downtime_p95:g}",
                     f"{a.downtime_max:g}", f"{a.p_any_downtime:.1%}", f"{a.availability_mean:.1%}"])
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(headers)]
    for cells in [headers, ["-" * w for w in widths], *rows]:
        print("  ".join(c.ljust(w) for c, w in zip(cells, widths)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Branchpoint experiment.")
    parser.add_argument("experiment", help="path to an experiment JSON file")
    parser.add_argument("--timeline", nargs="*", metavar="SCENARIO",
                        help="print the event log (all scenarios, or the ones named)")
    parser.add_argument("--explain", action="append", default=[], metavar="SCENARIO:COMPONENT",
                        help="trace a component's worst status back to its root cause")
    parser.add_argument("--json", metavar="FILE", help="write full results to a JSON file")
    parser.add_argument("--montecarlo", type=int, metavar="N",
                        help="also run each scenario N times with different seeds")
    args = parser.parse_args(argv)

    exp = load_experiment_file(args.experiment)
    graph = DependencyGraph(exp.system)
    print(f"System: {exp.system.name} ({len(exp.system.components)} components, "
          f"{len(exp.system.dependencies)} dependencies)")
    cycle = graph.find_cycle()
    if cycle:
        print(f"Warning: dependency cycle {' -> '.join(cycle)}")

    results = [run_scenario(exp.system, s, exp.until) for s in exp.scenarios]
    by_id = {r.scenario_id: r for r in results}

    print(f"\nSimulated {exp.until:g} time units per scenario.\n")
    print(comparison_table(results))

    if args.timeline is not None:
        for r in results:
            if not args.timeline or r.scenario_id in args.timeline:
                print_timeline(r)

    for item in args.explain:
        scenario_id, _, component_id = item.partition(":")
        if scenario_id not in by_id:
            print(f"\nUnknown scenario {scenario_id!r}", file=sys.stderr)
            return 1
        print_explanation(by_id[scenario_id], component_id)

    if args.montecarlo:
        print_monte_carlo([run_monte_carlo(exp.system, s, exp.until, args.montecarlo)
                           for s in exp.scenarios])

    if args.json:
        with open(args.json, "w") as f:
            json.dump({"until": exp.until, "results": [r.to_dict() for r in results]}, f, indent=2)
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
