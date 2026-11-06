# Branchpoint

Model an interconnected system, introduce failures, simulate how they spread,
and compare different decisions before applying them in the real world.

**Status:** Weeks 1–5 engine milestone. The deterministic discrete-event engine,
propagation, branching, metrics and CLI work. API, database and frontend come next.

## Quick start

```bash
cd backend
pip install -r requirements.txt
python -m pytest                     # run the tests
python -m app.cli ../examples/ecommerce.json
python -m app.cli ../examples/ecommerce.json --timeline db-down --explain db-down:api_gateway
```

Example output:

```
Scenario                        Availability  Downtime  Degraded  Affected  Recovery  Cost
Baseline (no incidents)         100.0%        0         0         0         -         0
DB fails, no intervention       66.7%         10        0         3         12        0
DB fails + cache fallback       100.0%        0         10        3         12        50
DB fails + read replica         100.0%        0         0         1         10        300
DB fails + fast restore at t=8  90.0%         3         0         3         5         0
2x traffic spike on gateway     100.0%        0         5         1         5         0
```

## Layout

```
backend/app/
  models/          Component, Dependency, Event, System (+ validation, JSON in/out)
  simulation/
    graph.py       BFS blast radius, DFS cycle detection, Kahn topological sort
    event_queue.py heapq priority queue with deterministic tie-breaking
    state.py       per-run state, status timelines, causal event log
    engine.py      discrete-event loop (domain-independent) + explain()
    metrics.py     availability, downtime, degraded time, recovery time, cost
    branching.py   Scenario inheritance, Interventions, run_scenario, comparison
  domains/
    base.py        DomainRules contract: intrinsic_status + effective_status
    infrastructure/rules.py   software-infrastructure propagation rules
    registry.py    domain name -> rules
  config.py        load an experiment JSON file
  cli.py           command-line runner
examples/ecommerce.json   the section-12 test system with 6 scenarios
```

## How the simulation works

1. Every event becomes a START (and END, if it has a duration) in a priority
   queue ordered by `(time, priority, insertion order)`.
2. START/END add or remove an *effect* on a component, then re-evaluate it.
3. The domain rules turn the effects into the component's own status, then
   combine that with its dependencies' statuses into an effective status.
4. If the status changed, the change is logged *with a pointer to its cause*,
   and every dependent is scheduled for re-evaluation after the dependency's
   `propagation_delay`.

Because each log entry points to its cause, every impact can be traced back to
the original event (`--explain`).

### Dependency semantics

`source_id` **depends on** `target_id`.

| type       | meaning                                                         |
|------------|-----------------------------------------------------------------|
| `requires` | source fails or degrades along with the target                  |
| `optional` | losing the target only degrades the source                      |
| `fallback` | stands in for the target, but the source runs degraded          |

Dependencies with the same `group` on the same source are interchangeable: the
source only needs **one** of them up. That is how replicas and fallbacks work.

### Events

`component_failure`, `component_recovery`, `traffic_spike` (severity = load
multiplier, compared to `capacity` / `capacity * overload_failure_ratio`),
`latency_increase`. Set `probability < 1` to make an event probabilistic.
Sampling uses the scenario's `seed`, so results are reproducible.

### Scenarios and branching

A scenario has a `parent`. It inherits the parent's events and interventions,
can add or override them by id, and can drop events with `remove_events`.
Each run deep-copies the base system, applies interventions to the copy, and
runs on that copy, so branches never affect each other.

## Assumptions and limitations

- Branchpoint is a simulation based on user-defined rules. It is not a
  production reliability predictor.
- Traffic spikes affect only their target. Load does not yet flow downstream.
- A delayed re-evaluation reads the dependency's status when it runs, so
  blips shorter than a propagation delay can be absorbed.
- Circular hard dependencies deadlock once both sides fail (the CLI warns
  about cycles).

## Next steps (roadmap)

- Week 6: FastAPI endpoints plus PostgreSQL persistence around `run_scenario`
- Weeks 7–8: React + React Flow editor, scenario builder, timeline view
- Week 9: Monte Carlo runs (repeated seeds, expected and p95 downtime)
- Week 10: benchmarks on synthetic graphs, docs, demo
