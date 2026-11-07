# Branchpoint: project context for Claude

Read this first. It describes what Branchpoint is, what is already built,
how the code is organised, the rules the code follows, and what to build next.

## 1. What Branchpoint is

An alternative-future simulation and decision-intelligence platform, built as a
second-year SWE portfolio project.

> Explore alternative futures. Make better decisions.

One shared simulation kernel runs three domains: **software infrastructure**
(failure propagation), **hospital operations** (patient-flow queueing) and
**cold-chain logistics** (stock, routing and refrigeration). A decision layer
scores branches against weighted objectives and constraints.

Main differentiator: **reproducible, branch-based experiments with explainable
cause chains, uncertainty and decision scoring.**

- Branches: compare interventions (replica, fallback, fast restore) from the same starting conditions.
- Explainability: every status change links to its cause, back to the original event.
- Reproducibility: each run stores a snapshot plus a seed, so replaying gives an identical result.
- Uncertainty: events can be probabilistic. Monte Carlo runs a scenario N times and reports expected / p95 outcomes.

Honesty rules: no fabricated results (every number shown comes from a run), no
claims of real-world data, no clinical claims (hospital), no product-safety
judgements (cold chain: "discarded" = exposure over the user's tolerance).

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
| 10 | Benchmarks, profiling, docs, demo video | Done |

Then the 8-phase multi-domain plan in `docs/ROADMAP.md`: all done (kernel and
catalogs, decision layer, catalog-driven frontend with the Futures dashboard,
hospital, cold chain, hardening, deployment config). Creating the hosted service
needs the owner's account (`docs/DEPLOY.md`).

Test status: 167 backend tests (pass on SQLite and PostgreSQL 16), 28 frontend unit tests, TypeScript type check clean, and the Playwright
end-to-end smoke test across all three domains passes. CI builds and smoke-tests the Docker image.

The owner is a student learning as they go. Explain the reasoning behind
changes, and keep code readable rather than clever.

## 3. Tech stack

| Layer | Choice |
|---|---|
| Simulation engine | Python 3.12+, standard library only |
| API | FastAPI, Pydantic v2 |
| Database | SQLAlchemy 2 ORM; PostgreSQL 16 (JSONB) in Docker, SQLite file when `DATABASE_URL` is unset |
| Frontend | React 18 + TypeScript 5 + Vite 6, React Router 7 |
| Graph editor | @xyflow/react (React Flow v12) |
| Charts | Recharts 3 |
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
    kernel.py        Kernel: shared discrete-event loop (clock, queue, seeded RNG + named streams, causal log, step guard)
    outcome.py       Outcome (metrics, log, timelines, series) and MetricValues returned by every domain
    event_queue.py   heapq queue ordered by (time, priority, insertion counter)
    state.py         SimulationState, Effect, LogEntry (cause_id links)
    engine.py        Simulator (infrastructure status propagation on the Kernel), explain(), first_change()
    metrics.py       Metrics, time_in_status, worst_of, compute_metrics
    branching.py     Intervention, Scenario (parent inheritance), run_scenario, comparison_table
    stats.py         percentile (shared)
    montecarlo.py    run_monte_carlo (seed base_seed + i), percentile, metric_stats, risk drivers, to_dict
  decision/          model.py (Objective, Constraint, DecisionModel, default_model), evaluate.py (scores,
                     ranking, Pareto, weight robustness), insights.py (sentences from numbers), sensitivity.py
  domains/
    spec.py          DomainSpec catalog: entity/relationship/event/intervention types, metrics (better=lower/higher), assumptions
    base.py          Domain ABC (spec, simulate() -> Outcome, errors()) and DomainRules ABC
    infrastructure/  spec.py (INFRASTRUCTURE_SPEC), domain.py (InfrastructureDomain), rules.py (InfrastructureRules)
    hospital/        spec.py (HOSPITAL_SPEC), model.py (HospitalModel queueing DES, HospitalDomain)
    coldchain/       spec.py (COLDCHAIN_SPEC), model.py (ColdChainModel: demand, (s,Q) orders, Dijkstra, exposure)
    registry.py      get_domain(name), register_domain(), all_domains(), known_*_types()
  config.py          load experiment JSON -> Experiment(system, scenarios, until)
  cli.py             command-line runner
  database/          session.py (Database, make_engine), tables.py (SQLAlchemy models),
                     migrate.py + migrations/ (Alembic; applied on startup), alembic.ini in backend/
  schemas.py         Pydantic API models (mirrored in frontend/src/api/types.ts)
  services/          systems, scenarios, runs, montecarlo, decisions, experiments, errors (business logic + transactions)
  api/               domains.py (GET /domains catalog), decisions.py (objectives, evaluate, sensitivity), systems.py, scenarios.py, simulations.py routers, deps.py
  main.py            create_app(): CORS, error handler, routers under /api, serves frontend/dist
  tests/             test_graph, test_engine, test_branching, test_montecarlo, test_kernel, test_migrations, test_infrastructure_metrics,
                     test_decision, test_domains, test_cli, test_api, conftest
frontend/src/
  api/               client.ts (fetch wrapper), types.ts, useDomains.ts (catalog cache)
  pages/             LandingPage (/), ProjectsPage (/systems), SystemWorkspace (+ workspace.ts context, incl. spec), DesignPage,
                     ScenariosPage, FuturesPage (decision dashboard), RunPage (playback + series charts), ComparePage
  components/        graph.tsx (node/edge rendering), Inspectors.tsx, ScenarioForms.tsx,
                     common.tsx (incl. Metric tile), Toast.tsx, TopBar.tsx, MonteCarloPanel.tsx
  lib/               domains.ts (catalog helpers), examples.ts, theme.ts (chart colours), catalog.ts (uniqueId),
                     layout.ts, timeline.ts, presets.ts, histogram.ts (+ lib.test.ts, domains.test.ts)
  examples/*.json    copies of the three examples
frontend/e2e/smoke.mjs      Playwright end-to-end workflow test
examples/                   ecommerce.json, hospital.json, coldchain.json (system + scenario tree + objectives each)
benchmarks/                 run_benchmarks.py, domains.py, requirements.txt, results/ (CSV + cProfile output)
docs/DEPLOY.md              Render / Docker hosting; render.yaml; .github/workflows/ci.yml
docs/ROADMAP.md             multi-domain plan (phases 1-8), domain model designs, decision layer
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
- A domain is a plug-in: a `DomainSpec` (catalog served at `GET /api/domains`) plus a `Domain` subclass whose
  `simulate(system, events, until, seed, intervention_cost=...)` returns an `Outcome`. Register it in `domains/registry.py`.
  Branching, Monte Carlo, comparison, persistence and the API are written against this interface, never against one domain.
- Comparison picks the best value per metric from the spec's `better` field; never hard-code metric names outside a domain.
- Domain randomness uses `kernel.stream("name")` so unrelated random draws don't shift each other (common random numbers).

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
- `traffic_spike`: `severity` is the load multiplier. Load above `capacity` gives DEGRADED; above `capacity * overload_failure_ratio` (default 1.5) gives FAILED. It only affects its target, unless a dependency has a `load_share` attribute: then that share of the caller's extra load is forwarded (an `inherited_load` effect, logged with its cause).
- `latency_increase`: DEGRADED.
- `probability < 1` makes an event probabilistic. It is sampled with `random.Random(seed)`, with events sorted by `(start_time, id)` first, so results don't depend on input order.

### Engine loop
Events are pushed as START and END items. Priority at equal time is END, then START, then EVALUATE, with an insertion counter as the tie-break, which makes runs deterministic. Every status change logs a `LogEntry` with `cause_id` and schedules EVALUATE for its dependents. There is a `max_steps` guard against oscillation. Cycles are allowed but warned about: hard cycles deadlock once both sides fail.

### Metrics
Measured at entry-point components (all components if none are marked):
`availability` (fraction of time not FAILED), `downtime`, `degraded_time`,
`affected_components` (ever left HEALTHY), `recovery_time` (first problem until all
healthy again; None if not recovered), and `cost` (sum of intervention costs).
Opt-in (None without the data, never invent a 0): `mean_latency`, `peak_latency` (component `latency`;
only components slow *themselves*, per `state.intrinsic`, get `degraded_latency_factor`),
`sla_breach_time` (`latency_sla` parameter), `peak_utilisation` (`capacity`), `running_cost` and
`total_cost` (`cost_per_time`).

### Decision layer
- Objectives (metric + weight, direction from the catalog) and constraints (`<=`/`>=`, optional
  `confidence` for chance constraints) live in `systems.objectives`; `{}` means the domain's `default_objectives`.
- Scores are min-max normalised across the compared futures (relative, 0..1), infeasible futures rank last,
  Pareto set and weight robustness are reported. Insights are generated only from computed numbers.
- Evaluations and sensitivity are computed live, not stored.

### Scenarios and branching
- A child inherits its parent's events (overridable by the same id, or removable with `remove_events`) and its interventions.
- Seed: a scenario without its own seed inherits the parent's, else 42.
- Interventions (`add_component`, `remove_component`, `add_dependency`, `remove_dependency`, `set_attribute`,
  `set_dependency_attribute`, `set_parameter`) are applied to a **deep copy** of the system, never the original.
- Validation (`services/scenarios.check`) dry-runs a scenario and all its descendants. Events may target components that an intervention adds.
- A system edit that would break any scenario is refused with 422.
- A scenario that has children cannot be deleted (409). Deleting a system removes scenarios leaf-first.

### Runs
A run stores `system_snapshot` (the base system), `scenario_snapshot` (resolved
events and interventions, plus the seed), metrics, timelines, and the log
(`simulation_events`). `POST /runs/{id}/replay` re-runs from the snapshots and must
be identical. `RunOut.system` is the system with interventions applied, which the playback view renders.

### API (all under /api)
- Domains: `GET /domains`, `GET /domains/{name}` (the catalogs)
- Systems: `GET/POST /systems`, `GET/PUT/DELETE /systems/{id}`, `GET /systems/{id}/analysis`, `POST /analysis`
- Import/export: `POST /experiments/import`, `GET /systems/{id}/export`
- Scenarios: `GET/POST /systems/{id}/scenarios`, `GET/PUT/DELETE /scenarios/{id}`, `POST /scenarios/{id}/branch`
- Runs: `POST/GET /scenarios/{id}/runs`, `GET /runs/{id}`, `GET /runs/{id}/explain/{seq}`, `POST /runs/{id}/replay`
- Comparison: `POST /compare`, with either `run_ids` or `scenario_ids` plus `until`
- Decisions: `GET/PUT /systems/{id}/objectives`, `POST /systems/{id}/evaluate` (`scenario_ids?`, `runs`, `model?` to try unsaved weights), `POST /scenarios/{id}/sensitivity`
- Monte Carlo: `POST/GET /scenarios/{id}/montecarlo` (`{runs: 1..10000, until, base_seed?}`), `GET /montecarlo/{id}`

### Database
The tables are `systems`, `components`, `dependencies`, `scenarios` (self-referencing
`parent_id`, ON DELETE RESTRICT), `scenario_events`, `interventions`,
`simulation_runs`, `simulation_events`, and `monte_carlo_runs` (JSONB `summary` with
aggregates + one downtime per run, and a `scenario_snapshot`; cascades from its scenario).

- User-facing ids such as "postgres" are stored as `key`, unique per parent; each row also has a surrogate primary key.
- The schema is managed by Alembic (`database/migrations/versions/`); `create_tables()` runs `migrate()` on startup, which stamps a pre-migration database at `0001` and then upgrades. New column? Add it to `tables.py`, run `alembic revision --autogenerate -m "..."` from `backend`, swap JSON types for `JSONType`, give non-null columns a `server_default`, and add a test in `test_migrations.py`.
- JSON columns `systems.parameters`, `dependencies.attributes`, `scenario_events.params` and `simulation_runs.series` hold domain-specific data.
- When replacing child rows, call `.clear()`, then `flush()`, then add the new rows, to avoid unique-key clashes.

### Frontend conventions
- `src/api/types.ts` must mirror `backend/app/schemas.py`; update both together.
- Pure logic lives in `src/lib/` and gets vitest tests.
- The Design tab edits a local draft (unsaved changes are marked with •). Scenarios always run against the **saved** system.
- Component canvas positions are saved in `component.layout` ({x, y}).
- The replica and fallback presets in `lib/presets.ts` regroup an ungrouped dependency first; otherwise a replica has no effect.
- Colours are CSS variables in `styles.css` (chart colours in `lib/theme.ts`). No UI framework. Design: Muddy
  (#5A3B22) background with soft glows and a faint grid, Cinnamon-tinted frosted-glass panels (glassmorphism),
  cream text, a dark mud-glass graph stage with gold connection lines. Each meaning has one hue:
  mint = healthy, orange = degraded, crimson = failed, blue = information/charts, lavender = probability/cause chain.
- Screens are catalog-driven (`lib/domains.ts`); never hard-code one domain's types or metrics in a page.
- Routes: `/` landing page, `/systems` list, `/systems/:id/{design,scenarios,futures,compare,runs/:runId}`.
  Links inside the workspace must be absolute (React Router 7 resolves relative links inside a `/*` route
  from the current page).

## 7. Known limitations (be honest about these in the README)
- Branchpoint's models are simplified and illustrative, not predictors (see README limitations per domain).
- Load only flows along dependencies with a `load_share`, instantly; latency ignores queueing.
- Decision scores are relative to the compared futures and depend on the chosen weights.
- Hard circular dependencies cannot recover.
- There is no authentication; a deployed instance is editable by anyone with the link.
- The Docker image is verified in CI only; the hosted service needs the owner's account.
- The frontend has no component tests beyond `lib/` and the e2e script.
- Monte Carlo runs are sequential and only as good as the probabilities entered.

## 8. What is left

- Create the hosted service (Render blueprint ready; needs the owner's account) and put the URL in the README.
- Record a narrated demo video (a silent walkthrough recording exists in docs/demo/).
- Ideas: urgency levels (hospital), back-orders and shelf life (cold chain), parallel Monte Carlo, accounts.

## 9. Working agreements for Claude
- Run `cd backend && python -m pytest` and `cd frontend && npm test && npx tsc -b` before saying work is done. Report failures honestly.
- Add tests for new engine behaviour first, with small hand-verifiable cases.
- Don't add AI/LLM features unless asked. The roadmap says ML only with a defensible prediction task.
- Commit in small, descriptive commits. Never commit `node_modules`, `dist`, `*.db` or `.venv`.
- Keep `examples/*.json` and `frontend/src/examples/*.json` identical.
- A new domain = `domains/<name>/spec.py` + model with `simulate()`, register it, add an example, tests.
  The frontend needs no changes unless the domain wants a new `features` flag.

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
