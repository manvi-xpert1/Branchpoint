# Branchpoint: project context for Claude

Read this first. It describes what Branchpoint is, what is already built,
how the code is organised, the rules the code follows, and what to build next.

## 1. What Branchpoint is

A failure-simulation and decision tool for software infrastructure, built as a
second-year SWE portfolio project.

> Model an interconnected system, introduce failures, simulate how they spread,
> and compare different decisions before applying them in the real world.

Main differentiator: **reproducible, branch-based failure experiments with
explainable impact propagation.**

- Branches: compare interventions (replica, fallback, fast restore) from the same starting conditions.
- Explainability: every status change links to its cause, back to the original event.
- Reproducibility: each run stores a snapshot plus a seed, so replaying gives an identical result.
- Uncertainty: events can be probabilistic. Monte Carlo runs a scenario N times and reports expected / p95 outcomes.

Product direction: software infrastructure first. The engine is domain-independent
so a second domain (supply chain) can be added later without rewriting it.

## 2. Status (10-week roadmap)

| Week | Topic | Status |
|---|---|---|
| 1 | Graph model, validation, BFS/DFS, CLI | Done |
| 2 | Deterministic failure propagation | Done |
| 3 | Discrete-event engine (priority queue, clock, history) | Done |
| 4 | Scenario branching + interventions | Done |
| 5 | Metrics + comparison + CLI report | Done |
| 6 | FastAPI + PostgreSQL persistence | Done |
| 7 | React + React Flow visual designer | Done |
| 8 | Scenario builder, playback, comparison UI | Done |
| 9 | Probabilistic simulation: Monte Carlo, expected/p95 outcomes | Done |
| 10 | Benchmarks, profiling, docs, demo video | Done except the demo video |

Test status: 71 backend tests (pass on SQLite and PostgreSQL 16), 17 frontend unit tests, TypeScript type check clean, and the Playwright
end-to-end smoke test (now including Monte Carlo) passes. The Docker build has not been
verified on a real machine yet.

The owner is a student learning as they go. Explain the reasoning behind
changes, and keep code readable rather than clever.

## 3. Tech stack

| Layer | Choice |
|---|---|
| Simulation engine | Python 3.12+, standard library only |
| API | FastAPI, Pydantic v2 |
| Database | SQLAlchemy 2 ORM; PostgreSQL 16 (JSONB) in Docker, SQLite file when `DATABASE_URL` is unset |
| Frontend | React 18 + TypeScript 5 + Vite 6 |
| Graph editor | @xyflow/react (React Flow v12) |
| Charts | Recharts |
| Tests | pytest, vitest, Playwright (e2e script) |
| Packaging | Multi-stage Dockerfile (builds the frontend, FastAPI serves it) + docker-compose with Postgres |

## 4. How to run (Windows)

**Docker (everything):** from the repo root run `docker compose up --build`, then open
http://localhost:8000 (app) or http://localhost:8000/docs (API).

**Local development, two terminals:**

```
# terminal 1: backend (SQLite by default)
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload          # http://localhost:8000

# terminal 2: frontend (proxies /api to :8000)
cd frontend
npm install
npm run dev                            # http://localhost:5173
```

If PowerShell blocks `activate`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

**Tests:**

```
cd backend;  python -m pytest
cd frontend; npm test;  npx tsc -b
```

To run the API tests against Postgres, set `TEST_DATABASE_URL`, for example
`postgresql+psycopg://branchpoint:branchpoint@localhost:5432/branchpoint_test`.

**CLI (engine only):** from `backend`, run `python -m app.cli ../examples/ecommerce.json --timeline db-down --explain db-down:api_gateway`
(add `--montecarlo 1000` for the Monte Carlo table).

**Benchmarks:** from the repo root, `pip install -r benchmarks/requirements.txt` (matplotlib, for charts only),
then `python benchmarks/run_benchmarks.py` (about 30 s; `--quick` for a smoke test). Writes
`benchmarks/results/*.csv`, `benchmarks/results/profile.txt` and `docs/benchmarks/*.png`.

## 5. Repository map

```
backend/app/
  models/            Component, Status, Dependency, Event, System (+ validate, to/from dict)
  simulation/
    graph.py         DependencyGraph: impact_bfs, find_cycle (iterative DFS), topological_order (Kahn)
    event_queue.py   heapq queue ordered by (time, priority, insertion counter)
    state.py         SimulationState, Effect, LogEntry (cause_id links)
    engine.py        Simulator (domain-independent loop), explain(), first_change()
    metrics.py       Metrics, time_in_status, worst_of, compute_metrics
    branching.py     Intervention, Scenario (parent inheritance), run_scenario, comparison_table
    montecarlo.py    run_monte_carlo (seed base_seed + i), percentile, MonteCarloResult.to_dict
  domains/
    base.py          DomainRules ABC: intrinsic_status(), effective_status(), validate()
    infrastructure/rules.py   InfrastructureRules
    registry.py      get_domain(name), register_domain()
  config.py          load experiment JSON -> Experiment(system, scenarios, until)
  cli.py             command-line runner
  database/          session.py (Database, make_engine), tables.py (SQLAlchemy models)
  schemas.py         Pydantic API models (mirrored in frontend/src/api/types.ts)
  services/          systems, scenarios, runs, montecarlo, experiments, errors (business logic + transactions)
  api/               systems.py, scenarios.py, simulations.py routers, deps.py
  main.py            create_app(): CORS, error handler, routers under /api, serves frontend/dist
  tests/             test_graph, test_engine, test_branching, test_montecarlo, test_api, conftest
frontend/src/
  api/               client.ts (fetch wrapper), types.ts
  pages/             ProjectsPage, SystemWorkspace (+ workspace.ts context), DesignPage,
                     ScenariosPage, RunPage (playback), ComparePage
  components/        graph.tsx (node/edge rendering), Inspectors.tsx, ScenarioForms.tsx,
                     common.tsx (incl. Metric tile), Toast.tsx, TopBar.tsx, MonteCarloPanel.tsx
  lib/               catalog.ts, layout.ts, timeline.ts, presets.ts, histogram.ts (+ lib.test.ts)
  examples/ecommerce.json   copy of the example used by the "Load example" button
frontend/e2e/smoke.mjs      Playwright end-to-end workflow test
examples/ecommerce.json     example system + 7 scenarios (the reference experiment; "flaky" is probabilistic)
benchmarks/                 run_benchmarks.py, requirements.txt, results/ (CSV + cProfile output)
docs/architecture.md        layers, engine loop, persistence, Monte Carlo, testing, performance
docs/benchmarks/            benchmark charts used in README
docs/screenshots/           screenshots used in README
Dockerfile, docker-compose.yml, README.md
```

## 6. Core concepts and rules (do not break these)

### Layering
- `simulation/` and `domains/` must **never** import FastAPI, SQLAlchemy or anything web-related. The engine must stay runnable from a plain Python script or the CLI.
- `api/` holds HTTP only: it calls `services/`, which own transactions and validation. Services raise `NotFound` (404), `Conflict` (409) or `InvalidInput` (422) from `services/errors.py`.
- The domain layer holds what infrastructure means; the engine holds time, queueing, effects and logging.

### Dependency direction
`source_id` **depends on** `target_id`. When the target breaks, the effect flows to
the source. In the UI, edges go from a component's bottom handle to its dependency,
and the arrow points at the dependency.

### Dependency types and groups
- `requires`: the source fails or degrades with the target.
- `optional`: losing the target only degrades the source.
- `fallback`: stands in for the target, but the source runs at most DEGRADED.
- `group`: dependencies with the same group on the same source are interchangeable; the source needs one healthy member. No group means the dependency is its own group. Replicas and fallbacks only help when they share a group with the primary.
- `propagation_delay`: time before a change reaches the dependent. A delayed evaluation reads status when it runs, so blips shorter than the delay can be absorbed. This is documented and intended.

### Statuses
`Status` is an IntEnum: HEALTHY=0, DEGRADED=1, FAILED=2. Higher is worse, so `max()` gives the worse status and `min()` the better.

### Events (4 types)
- `component_failure`: FAILED. With no `duration`, the component's `recovery_time` attribute is used if set.
- `component_recovery`: clears failure effects.
- `traffic_spike`: `severity` is the load multiplier. Load above `capacity` gives DEGRADED; above `capacity * overload_failure_ratio` (default 1.5) gives FAILED. It only affects its target (a known limitation).
- `latency_increase`: DEGRADED.
- `probability < 1` makes an event probabilistic. It is sampled with `random.Random(seed)`, with events sorted by `(start_time, id)` first, so results don't depend on input order.

### Engine loop
Events are pushed as START and END items. Priority at equal time is END, then START, then EVALUATE, with an insertion counter as the tie-break, which makes runs deterministic. Every status change logs a `LogEntry` with `cause_id` and schedules EVALUATE for its dependents. There is a `max_steps` guard against oscillation. Cycles are allowed but warned about: hard cycles deadlock once both sides fail.

### Metrics
Measured at entry-point components (all components if none are marked):
`availability` (fraction of time not FAILED), `downtime`, `degraded_time`,
`affected_components` (ever left HEALTHY), `recovery_time` (first problem until all
healthy again; None if not recovered), and `cost` (sum of intervention costs).

### Scenarios and branching
- A child inherits its parent's events (overridable by the same id, or removable with `remove_events`) and its interventions.
- Seed: a scenario without its own seed inherits the parent's, else 42.
- Interventions (`add_component`, `remove_component`, `add_dependency`, `remove_dependency`, `set_attribute`) are applied to a **deep copy** of the system, never the original.
- Validation (`services/scenarios.check`) dry-runs a scenario and all its descendants. Events may target components that an intervention adds.
- A system edit that would break any scenario is refused with 422.
- A scenario that has children cannot be deleted (409). Deleting a system removes scenarios leaf-first.

### Runs
A run stores `system_snapshot` (the base system), `scenario_snapshot` (resolved
events and interventions, plus the seed), metrics, timelines, and the log
(`simulation_events`). `POST /runs/{id}/replay` re-runs from the snapshots and must
be identical. `RunOut.system` is the system with interventions applied, which the playback view renders.

### API (all under /api)
- Systems: `GET/POST /systems`, `GET/PUT/DELETE /systems/{id}`, `GET /systems/{id}/analysis`, `POST /analysis`
- Import/export: `POST /experiments/import`, `GET /systems/{id}/export`
- Scenarios: `GET/POST /systems/{id}/scenarios`, `GET/PUT/DELETE /scenarios/{id}`, `POST /scenarios/{id}/branch`
- Runs: `POST/GET /scenarios/{id}/runs`, `GET /runs/{id}`, `GET /runs/{id}/explain/{seq}`, `POST /runs/{id}/replay`
- Comparison: `POST /compare`, with either `run_ids` or `scenario_ids` plus `until`
- Monte Carlo: `POST/GET /scenarios/{id}/montecarlo` (`{runs: 1..10000, until, base_seed?}`), `GET /montecarlo/{id}`

### Database
The tables are `systems`, `components`, `dependencies`, `scenarios` (self-referencing
`parent_id`, ON DELETE RESTRICT), `scenario_events`, `interventions`,
`simulation_runs`, `simulation_events`, and `monte_carlo_runs` (JSONB `summary` with
aggregates + one downtime per run, and a `scenario_snapshot`; cascades from its scenario).

- User-facing ids such as "postgres" are stored as `key`, unique per parent; each row also has a surrogate primary key.
- Tables are created on startup with `create_all`; there are no Alembic migrations yet.
- When replacing child rows, call `.clear()`, then `flush()`, then add the new rows, to avoid unique-key clashes.

### Frontend conventions
- `src/api/types.ts` must mirror `backend/app/schemas.py`; update both together.
- Pure logic lives in `src/lib/` and gets vitest tests.
- The Design tab edits a local draft (unsaved changes are marked with •). Scenarios always run against the **saved** system.
- Component canvas positions are saved in `component.layout` ({x, y}).
- The replica and fallback presets in `lib/presets.ts` regroup an ungrouped dependency first; otherwise a replica has no effect.
- Colours are CSS variables in `styles.css`. No UI framework is used.

## 7. Known limitations (be honest about these in the README)
- Branchpoint is a rule-based simulation, not a production reliability predictor.
- Traffic spikes don't propagate load downstream.
- Hard circular dependencies cannot recover.
- There are no database migrations (Alembic) yet.
- There is no authentication; this is a single-user local app.
- The Docker build has not been verified on a real machine yet.
- The frontend has no component tests beyond `lib/` and the e2e script.
- Monte Carlo runs are sequential and only as good as the probabilities entered.

## 8. Weeks 9 and 10: what was built, and what is left

Done:
- `simulation/montecarlo.py`: `run_monte_carlo(system, scenario, until, runs, base_seed=None)`.
  Run i uses seed `base_seed + i`; base seed defaults to the scenario's seed. Aggregates: mean,
  p50, p95, max downtime; `p_any_downtime`; mean availability and degraded time; `event_frequency`;
  `deterministic` (no event has probability < 1). Pure, standard library only.
- `POST /scenarios/{id}/montecarlo` stores a summary in `monte_carlo_runs` (not 1,000 logs).
- UI: "Run many times" panel on the scenario page (histogram with the p95 bar marked, metric tiles,
  event frequencies, "model estimates" notice); Compare page option adding expected and p95 downtime.
- CLI `--montecarlo N`.
- `benchmarks/run_benchmarks.py` (chains, trees, random DAGs at 10 to 10,000 nodes; event,
  branch and Monte Carlo counts; cProfile), charts in README, `docs/architecture.md`.

Left:
- Record the demo video (suggested flow: load example → design → branch "DB fails" and add a
  replica → run & playback with "why did this happen?" → Flaky week Monte Carlo → Compare with spread).
- Verify `docker compose up --build` on a real machine.

## 9. Working agreements for Claude
- Run `cd backend && python -m pytest` and `cd frontend && npm test && npx tsc -b` before saying work is done. Report failures honestly.
- Add tests for new engine behaviour first, with small hand-verifiable cases.
- Don't add AI/LLM features unless asked. The roadmap says ML only with a defensible prediction task.
- Commit in small, descriptive commits. Never commit `node_modules`, `dist`, `*.db` or `.venv`.
- Keep `examples/ecommerce.json` and `frontend/src/examples/ecommerce.json` identical.

## 10. GitHub
Remote: https://github.com/manvi-xpert1/Branchpoint

First push from the project folder:

```
git remote add origin https://github.com/manvi-xpert1/Branchpoint.git
git branch -M main
git push -u origin main
```

If the downloaded folder has no `.git` folder (hidden files were not copied), run
`git init`, then `git add -A`, then `git commit -m "Branchpoint weeks 1-8"` first.
