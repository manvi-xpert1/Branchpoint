"""Benchmarks for the Branchpoint engine.

Measures how simulation runtime grows with:

1. node count   (chain, tree and random DAG, 10 to 10,000 nodes)
2. event count  (1 to 1,000 failure events on a 1,000-node DAG)
3. branch count (1 to 64 scenarios branched from one parent)
4. Monte Carlo run count

and profiles the largest case with cProfile.

Run from the repo root:

    pip install -r benchmarks/requirements.txt     # matplotlib, only for the charts
    python benchmarks/run_benchmarks.py            # full run, a minute or two
    python benchmarks/run_benchmarks.py --quick    # small sizes, for a smoke test

Results go to benchmarks/results/ (CSV + profile) and the charts to
docs/benchmarks/ (PNG), which the README embeds.

Each timing is the fastest of several repeats (min is the usual choice
for benchmarks: slower repeats are noise from the OS, not the code).
Graphs are generated from a fixed seed, so every run measures the same inputs.
"""

from __future__ import annotations

import argparse
import cProfile
import csv
import io
import pstats
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domains.infrastructure import InfrastructureRules  # noqa: E402
from app.models import Component, Dependency, Event, System  # noqa: E402
from app.simulation.branching import Intervention, Scenario, run_scenario  # noqa: E402
from app.simulation.engine import Simulator  # noqa: E402
from app.simulation.montecarlo import run_monte_carlo  # noqa: E402

RESULTS = ROOT / "benchmarks" / "results"
CHARTS = ROOT / "docs" / "benchmarks"
UNTIL = 100.0
# The engine's default guard is 100,000 steps; big graphs legitimately need more.
MAX_STEPS = 50_000_000


# ---- synthetic graphs ---------------------------------------------------
# In every shape, node 0 is the entry point and the event hits the node(s)
# that everything ultimately depends on, so the failure reaches the whole
# graph. That is the worst case for propagation.

def _system(n: int, edges: list[tuple[int, int]], name: str) -> System:
    s = System(id=name, name=name)
    for i in range(n):
        s.add_component(Component(f"n{i}", f"n{i}", "service", entry_point=(i == 0)))
    for k, (src, dst) in enumerate(edges):
        s.add_dependency(Dependency(f"d{k}", f"n{src}", f"n{dst}"))
    return s


def chain(n: int) -> System:
    """n0 -> n1 -> ... -> n(n-1): every node requires the next one."""
    return _system(n, [(i, i + 1) for i in range(n - 1)], f"chain-{n}")


def tree(n: int) -> System:
    """Binary tree where every node requires its parent; n0 is the shared root.

    Like many services sharing one database: failing n0 takes down all.
    """
    return _system(n, [(i, (i - 1) // 2) for i in range(1, n)], f"tree-{n}")


def random_dag(n: int, degree: int = 2, seed: int = 0) -> System:
    """Each node requires up to ``degree`` random higher-numbered nodes.

    Edges only point from lower to higher numbers, so there are no cycles.
    The last node is depended on by everything that reaches it.
    """
    rng = random.Random(seed)
    edges = []
    for i in range(n - 1):
        targets = {rng.randrange(i + 1, n) for _ in range(degree)}
        targets.add(i + 1)  # keep the graph connected
        edges.extend((i, t) for t in sorted(targets))
    return _system(n, edges, f"dag-{n}")


SHAPES = {"chain": chain, "tree": tree, "dag": random_dag}
# The node whose failure reaches every other node, per shape.
ROOT_NODE = {"chain": lambda n: f"n{n - 1}", "tree": lambda n: "n0", "dag": lambda n: f"n{n - 1}"}


# ---- timing ---------------------------------------------------------------
def best_of(fn, repeats: int) -> float:
    """Fastest wall-clock time of ``repeats`` calls, in milliseconds."""
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best * 1000


def simulate(system: System, events: list[Event]) -> tuple[int, int]:
    """One run. Returns (log entries, components that changed status)."""
    sim = Simulator(system, InfrastructureRules(), until=UNTIL, seed=0, max_steps=MAX_STEPS)
    sim.schedule(events)
    state = sim.run()
    changed = sum(1 for tl in state.timeline.values() if len(tl) > 1)
    return len(state.log), changed


def outage(target: str, eid: str = "outage", at: float = 1.0) -> Event:
    return Event(eid, "component_failure", target, at, duration=10.0)


# ---- experiments ----------------------------------------------------------
def bench_nodes(sizes: list[int], repeats: int) -> list[dict]:
    rows = []
    for shape, build in SHAPES.items():
        for n in sizes:
            system = build(n)
            event = [outage(ROOT_NODE[shape](n))]
            log_len, changed = simulate(system, event)
            ms = best_of(lambda: simulate(system, event), repeats if n < 5000 else 1)
            rows.append({"shape": shape, "nodes": n, "edges": len(system.dependencies),
                         "log_entries": log_len, "components_changed": changed, "ms": round(ms, 3)})
            print(f"  nodes  {shape:<5} n={n:<6} edges={len(system.dependencies):<6} "
                  f"changed={changed:<6} {ms:9.1f} ms")
    return rows


def bench_events(n: int, counts: list[int], repeats: int) -> list[dict]:
    system = random_dag(n)
    rng = random.Random(1)
    rows = []
    for k in counts:
        # k failures at random nodes and times, each lasting 5 time units.
        events = [Event(f"e{i}", "component_failure", f"n{rng.randrange(n)}",
                        round(rng.uniform(0, UNTIL - 10), 2), duration=5.0) for i in range(k)]
        log_len, _ = simulate(system, events)
        ms = best_of(lambda: simulate(system, events), repeats)
        rows.append({"nodes": n, "events": k, "log_entries": log_len, "ms": round(ms, 3)})
        print(f"  events n={n} events={k:<5} log={log_len:<7} {ms:9.1f} ms")
    return rows


def bench_branches(n: int, counts: list[int], repeats: int) -> list[dict]:
    """Each branch inherits one outage and adds its own intervention."""
    system = random_dag(n)
    parent = Scenario(id="parent", name="parent", events=[outage(f"n{n - 1}")])
    rows = []
    for b in counts:
        branches = [
            Scenario(id=f"b{i}", name=f"b{i}", parent=parent, interventions=[
                Intervention(f"iv{i}", "set_attribute",
                             {"component_id": f"n{i % n}", "key": "note", "value": i}),
            ])
            for i in range(b)
        ]

        def run_all() -> None:
            for s in branches:
                run_scenario(system, s, UNTIL)

        ms = best_of(run_all, repeats)
        rows.append({"nodes": n, "branches": b, "ms": round(ms, 3), "ms_per_branch": round(ms / b, 3)})
        print(f"  branch n={n} branches={b:<4} {ms:9.1f} ms ({ms / b:.1f} ms each)")
    return rows


def bench_monte_carlo(n: int, counts: list[int]) -> list[dict]:
    system = random_dag(n)
    scenario = Scenario(id="mc", name="mc", events=[
        Event("maybe", "component_failure", f"n{n - 1}", 1.0, duration=10.0, probability=0.5),
    ])
    rows = []
    for runs in counts:
        ms = best_of(lambda: run_monte_carlo(system, scenario, UNTIL, runs), 1)
        rows.append({"nodes": n, "runs": runs, "ms": round(ms, 3), "ms_per_run": round(ms / runs, 3)})
        print(f"  monte  n={n} runs={runs:<5} {ms:9.1f} ms ({ms / runs:.2f} ms each)")
    return rows


def profile_largest(n: int) -> str:
    system = random_dag(n)
    event = [outage(f"n{n - 1}")]
    profiler = cProfile.Profile()
    profiler.enable()
    simulate(system, event)
    profiler.disable()
    out = io.StringIO()
    stats = pstats.Stats(profiler, stream=out).strip_dirs().sort_stats("cumulative")
    out.write(f"cProfile of one run: random DAG, {n} nodes, {len(system.dependencies)} edges, "
              f"one outage that reaches every node.\n\n")
    stats.print_stats(20)
    return out.getvalue()


# ---- output -----------------------------------------------------------------
def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def draw_charts(nodes, events, branches, monte) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed: skipping charts (pip install -r benchmarks/requirements.txt)")
        return

    CHARTS.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": 0.3, "figure.dpi": 110})
    colours = {"chain": "#2563eb", "tree": "#16a34a", "dag": "#d97706"}

    def finish(fig, ax, name: str, title: str, xlabel: str, ylabel: str = "runtime (ms)") -> None:
        ax.set_title(title, loc="left", fontweight="bold")
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        fig.tight_layout()
        fig.savefig(CHARTS / name)
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.4, 4))
    for shape in SHAPES:
        pts = [r for r in nodes if r["shape"] == shape]
        ax.plot([r["nodes"] for r in pts], [r["ms"] for r in pts], "o-", label=shape, color=colours[shape])
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.legend(frameon=False)
    finish(fig, ax, "runtime_vs_nodes.png", "Runtime vs graph size (one outage reaching every node)",
           "components (log scale)", "runtime (ms, log scale)")

    fig, ax = plt.subplots(figsize=(6.4, 4))
    ax.plot([r["events"] for r in events], [r["ms"] for r in events], "o-", color="#dc2626")
    ax.set_xscale("log")
    ax.set_yscale("log")
    finish(fig, ax, "runtime_vs_events.png", f"Runtime vs event count ({events[0]['nodes']}-node DAG)",
           "failure events (log scale)", "runtime (ms, log scale)")

    fig, ax = plt.subplots(figsize=(6.4, 4))
    ax.plot([r["branches"] for r in branches], [r["ms"] for r in branches], "o-", color="#7c3aed",
            label="all branches")
    ax.legend(frameon=False)
    finish(fig, ax, "runtime_vs_branches.png", f"Runtime vs branch count ({branches[0]['nodes']}-node DAG)",
           "branches simulated")

    fig, ax = plt.subplots(figsize=(6.4, 4))
    ax.plot([r["runs"] for r in monte], [r["ms"] / 1000 for r in monte], "o-", color="#0891b2")
    finish(fig, ax, "runtime_vs_montecarlo.png", f"Monte Carlo time vs runs ({monte[0]['nodes']}-node DAG)",
           "Monte Carlo runs", "runtime (s)")
    print(f"Charts written to {CHARTS.relative_to(ROOT)}/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true", help="small sizes only (a few seconds)")
    args = parser.parse_args(argv)

    if args.quick:
        sizes, ev_n, ev_counts, br_n, br_counts, mc_n, mc_counts, reps = (
            [10, 100], 100, [1, 10, 50], 100, [1, 4], 50, [10, 50], 1)
    else:
        sizes, ev_n, ev_counts, br_n, br_counts, mc_n, mc_counts, reps = (
            [10, 100, 1000, 10_000], 1000, [1, 10, 100, 1000], 1000, [1, 4, 16, 64],
            100, [100, 500, 1000, 2000], 3)

    RESULTS.mkdir(parents=True, exist_ok=True)
    print(f"Python {sys.version.split()[0]}")
    print("Runtime vs node count")
    nodes = bench_nodes(sizes, reps)
    print("Runtime vs event count")
    events = bench_events(ev_n, ev_counts, reps)
    print("Runtime vs branch count")
    branches = bench_branches(br_n, br_counts, reps)
    print("Monte Carlo")
    monte = bench_monte_carlo(mc_n, mc_counts)

    write_csv(RESULTS / "nodes.csv", nodes)
    write_csv(RESULTS / "events.csv", events)
    write_csv(RESULTS / "branches.csv", branches)
    write_csv(RESULTS / "montecarlo.csv", monte)
    (RESULTS / "profile.txt").write_text(profile_largest(sizes[-1]))
    print(f"Results written to {RESULTS.relative_to(ROOT)}/")
    draw_charts(nodes, events, branches, monte)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
