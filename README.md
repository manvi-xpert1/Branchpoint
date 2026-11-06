# Branchpoint

Model an interconnected system, introduce failures, simulate how they spread,
and compare different decisions before applying them in the real world.

**Status:** Week 8 complete. You can design systems visually, build scenarios, watch
failures spread, and compare decisions in the browser.

![Playback of a database failure, with the root-cause chain](docs/screenshots/playback.png)

## What you can do

| Screen | What it does |
|---|---|
| **Systems** | List, create, delete; load the built-in example; import an experiment JSON file |
| **Design** | Drag-and-drop graph editor (React Flow): add components, connect dependencies, edit attributes, live validation, cycle and blast-radius highlighting, JSON mode, export |
| **Scenarios** | Scenario tree with branching; events with timing, duration, load multiplier and probability; interventions with one-click *replica* and *fallback* presets |
| **Playback** | The graph coloured by status over time, play/scrub/step controls, per-component timeline lanes, event log, click any entry to see *why it happened*, replay verification |
| **Compare** | Run scenarios side by side, with the best value per metric highlighted and a downtime vs degraded chart |

| Design | Scenario builder | Compare |
|---|---|---|
| ![](docs/screenshots/designer.png) | ![](docs/screenshots/scenario-builder.png) | ![](docs/screenshots/compare.png) |

## Quick start

### Option A: Docker (everything in one command)

```bash
docker compose up --build
```

Open **http://localhost:8000** for the app, or http://localhost:8000/docs for the API.

### Option B: run locally for development

Backend (terminal 1). With no `DATABASE_URL` it uses a local SQLite file:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn app.main:app --reload     # http://localhost:8000
```

Frontend (terminal 2), with hot reload; it proxies `/api` to the backend:

```bash
cd frontend
npm install
npm run dev                       # http://localhost:5173
```

Set `DATABASE_URL` to use PostgreSQL instead of SQLite:
`postgresql+psycopg://branchpoint:branchpoint@localhost:5432/branchpoint`

### Tests

```bash
cd backend && python -m pytest          # 55 engine + API tests
cd frontend && npm test                 # 13 unit tests (layout, timelines, presets)
cd frontend && npx tsc -b               # type check
```

End-to-end (optional): with the app running on :8000, run
`npm i -D playwright && npx playwright install chromium && npm run e2e`.
It clicks through the full workflow in a real browser and saves screenshots.

### Command-line runner (engine only, no server)

```bash
cd backend
python -m app.cli ../examples/ecommerce.json
python -m app.cli ../examples/ecommerce.json --timeline db-down --explain db-down:api_gateway
```

### Try the API

1. In `/docs`, call `POST /api/experiments/import` with the contents of
   `examples/ecommerce.json`. It returns the new system and scenario ids.
2. `POST /api/compare` with `{"scenario_ids": ["<db-down id>", "<cache id>", "<replica id>"]}`
   runs all three and shows which is best on each metric.
3. Take a `seq` from a run's `log` and call `GET /api/runs/{id}/explain/{seq}`
   to see the causal chain.

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

## API

All routes are under `/api`. Full schemas are at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| GET / POST | `/systems` | list / create systems |
| GET / PUT / DELETE | `/systems/{id}` | read / replace definition / delete (cascades) |
| GET | `/systems/{id}/analysis` | cycles, topological order, blast radius, warnings |
| POST | `/analysis` | validate an unsaved definition (for live editor feedback) |
| GET / POST | `/systems/{id}/scenarios` | list / create scenarios (`parent_id` makes a branch) |
| GET / PUT / DELETE | `/scenarios/{id}` | includes resolved (inherited) events and lineage; delete returns 409 if branches exist |
| POST | `/scenarios/{id}/branch` | create an empty child that inherits everything |
| POST / GET | `/scenarios/{id}/runs` | run a simulation and store the result / list runs |
| GET | `/runs/{id}` | metrics, per-component timelines, causal event log |
| GET | `/runs/{id}/explain/{seq}` | root-cause chain for one log entry |
| POST | `/runs/{id}/replay` | re-run from the stored snapshot and verify it is identical |
| POST | `/compare` | compare existing `run_ids`, or run `scenario_ids` now |
| POST | `/experiments/import` | import an experiment JSON file (all or nothing) |
| GET | `/systems/{id}/export` | export system + scenario tree as experiment JSON |

Design choices:

- **Validation before storage.** Invalid graphs, events targeting unknown
  components, broken interventions and parent cycles return `422` with a
  reason. A system edit that would break an existing scenario is refused.
- **Reproducible runs.** Each run stores a snapshot of the exact system and
  resolved scenario it used, so `replay` gives an identical result even after
  the system has been edited.
- **Layered.** `api/` (HTTP) → `services/` (use cases, transactions) →
  `simulation/` + `domains/` (pure engine, no database or web code).

### Database tables

`systems`, `components`, `dependencies`, `scenarios` (self-referencing
`parent_id`), `scenario_events`, `interventions`, `simulation_runs` (with JSONB
metrics, snapshots and timelines), `simulation_events` (causally linked log).
Tables are created on startup. Alembic migrations will be added once the
schema settles.

## Layout

```
backend/app/
  main.py          FastAPI app factory, error handling, CORS
  schemas.py       Pydantic request/response models
  api/             HTTP routers: systems, scenarios, simulations
  services/        use cases: CRUD, validation, running, replay, compare, import/export
  database/        SQLAlchemy engine/session + table definitions
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

frontend/src/
  api/             typed API client + types mirroring backend schemas
  pages/           Projects, Design, Scenarios, Run (playback), Compare
  components/      graph node/edge rendering, inspectors, scenario forms
  lib/             pure logic with unit tests: layout, timeline, presets
frontend/e2e/smoke.mjs    Playwright end-to-end workflow test
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

- ~~Week 6: FastAPI endpoints plus PostgreSQL persistence~~ ✅
- ~~Weeks 7–8: React + React Flow editor, scenario builder, playback, comparison~~ ✅
- Week 9: Monte Carlo runs (repeated seeds, expected and p95 downtime)
- Week 10: benchmarks on synthetic graphs, docs, demo
