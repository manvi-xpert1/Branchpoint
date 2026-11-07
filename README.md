# Branchpoint

**Explore alternative futures. Make better decisions.**

Branchpoint is an alternative-future simulation and decision-intelligence platform. You model a
system, start from a situation (a database outage, a flu surge, a power cut), branch it once for every
decision you are weighing, and simulate where each branch leads, once with a fixed seed or hundreds of
times to see the spread. Branchpoint then scores the futures against what matters to you, shows the
trade-offs and the Pareto set, tells you which inputs the answer depends on, and explains every effect
back to its cause.

One shared simulation engine runs three domains:

| Domain | You model | You explore | Example |
|---|---|---|---|
| **Software infrastructure** | gateways, services, databases, caches, queues | outages, traffic spikes, slow dependencies; replicas, fallbacks, faster restores | `examples/ecommerce.json` |
| **Hospital operations** | patient arrivals, triage, emergency, diagnostics, wards, ICU | arrival surges, staff shortages, closures; extra beds/bays, faster discharges | `examples/hospital.json` |
| **Cold-chain logistics** | suppliers, cold warehouses, distribution centres, stores, refrigerated routes | power cuts, refrigeration failures, road closures, demand spikes; backup power, safety stock, rerouting | `examples/coldchain.json` |

The models are deliberately simple and the examples use made-up numbers: results are estimates from
your inputs, not predictions. The hospital model is an operational queueing model and makes no
clinical claims; the cold-chain model tracks exposure against a tolerance you set and does not judge
product safety. No real-world data sources are connected.

![Alternative futures dashboard for the hospital example](docs/screenshots/futures.png)

## What you can do

| Screen | What it does |
|---|---|
| **Landing** | Open any of the three examples straight into its futures dashboard, build your own, or import JSON |
| **Systems** | Create a system in any domain, load examples, import/export experiment files |
| **Design** | Drag-and-drop graph editor built from the domain's catalog: its component types, settings with units and help, connection types, system parameters, live validation, the model's assumptions, JSON mode |
| **Scenarios** | Scenario tree with branching; the domain's events (on components or on routes) with timing, severity and probability; decisions (change a setting, add/remove parts or routes, change a parameter) |
| **Futures** | The decision dashboard: weight sliders and hard limits (optionally "in X% of runs"), every future simulated and scored 0-100, recommended / Pareto / dominated / breaks-a-limit badges, a trade-off chart between any two metrics, plain-language insights generated from the numbers, a risk table with the main risk driver, a "what matters most" tornado chart, and the model's assumptions |
| **Playback** | The graph coloured by status over time (including closed routes), play/scrub/step, timeline lanes, charts of queues / stock / load / latency over time, an event log, and *why did this happen?* for any entry |
| **Compare** | Every metric side by side with the best value highlighted, a chart of any metric, and optionally the Monte Carlo mean and bad case |
| **Monte Carlo** | Run a scenario N times: histogram of the domain's risk metric, mean / p50 / bad case / worst 5% of runs, risk drivers, and the spread of every metric |

| Landing | Design (hospital) | Playback (cold chain) |
|---|---|---|
| ![](docs/screenshots/landing.png) | ![](docs/screenshots/designer.png) | ![](docs/screenshots/playback.png) |

**Demo:** [docs/demo/branchpoint-demo.mp4](docs/demo/branchpoint-demo.mp4) is a one-minute silent
walkthrough recorded from the real app (`frontend/e2e/demo.mjs` re-records it and the screenshots).

**Monte Carlo.** The "Flaky week" example has three events that each happen only with some
probability. A single seeded run happens to show no downtime; 1,000 runs show the real picture:
3.9 time units expected, 14 in the bad case, and the database outage as the main driver.

<img src="docs/screenshots/monte-carlo.png" alt="Monte Carlo panel with histogram and risk drivers" width="720">

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
cd backend && python -m pytest          # 166 engine, domain, decision and API tests (SQLite and PostgreSQL)
cd frontend && npm test                 # 28 unit tests (catalog helpers, layout, timelines, presets, histogram)
cd frontend && npx tsc -b               # type check
```

End-to-end (optional): build the frontend (`npm run build`), start the backend on :8000, then run
`npm i -D playwright && npx playwright install chromium && npm run e2e`.
It clicks through the full workflow in a real browser for all three domains (futures and weights,
sensitivity, designer, branching, a 1,000-run Monte Carlo, comparison, playback with cause chains,
hospital queue charts, a cold-chain reroute explained back to the road closure) and saves screenshots.
Set `CHROME_PATH` to use an already-installed Chrome instead. CI (`.github/workflows/ci.yml`) runs the
backend tests on SQLite and PostgreSQL, the frontend checks, and builds and smoke-tests the Docker image.

### Command-line runner (engine only, no server)

```bash
cd backend
python -m app.cli ../examples/ecommerce.json
python -m app.cli ../examples/ecommerce.json --timeline db-down --explain db-down:api_gateway
python -m app.cli ../examples/ecommerce.json --montecarlo 1000
python -m app.cli ../examples/ecommerce.json --evaluate db-down db-down-cache-fallback db-down-replica db-down-fast-restore
python -m app.cli ../examples/ecommerce.json --sensitivity flaky --runs 200
python -m app.cli ../examples/hospital.json --evaluate surge surge-ward-beds surge-ed-bays surge-discharge surge-icu
python -m app.cli ../examples/coldchain.json --evaluate outage outage-generator outage-lean
```

`--evaluate` scores the four ways of handling a database failure against the default
objectives (downtime x3, degraded time x1, intervention cost x1):

```
  1. DB fails + fast restore at t=8     score  82.0  [Pareto]
  2. DB fails + read replica            score  80.0  [Pareto]
  3. DB fails + cache fallback          score  76.7  [Pareto]
  4. DB fails, no intervention          score  40.0

  - DB fails + fast restore at t=8 ranks first with a score of 82/100: best on degraded time and intervention cost.
  - Choosing DB fails + fast restore at t=8 over DB fails + read replica means accepting worse downtime (3 vs 0).
  - DB fails, no intervention is dominated by DB fails + fast restore at t=8: it is at least as good on every objective and better on at least one.
  - The recommendation depends on the weights: doubling the weight of downtime would make DB fails + read replica the best choice.
  - Compared with DB fails, no intervention, DB fails + fast restore at t=8 improves downtime 10 → 3.
```

The hospital example finds that the ICU, not the ward, is the bottleneck during a flu surge, and that
extra ED bays help waiting times most but increase boarding:

```
  1. Surge + 4 extra ED bays                       score  71.5  [Pareto]
  2. Surge + 2 extra ICU beds                      score  33.6  [Pareto]
  3. Surge + faster discharges (discharge lounge)  score  27.8  [Pareto]
  4. Flu surge (+60% arrivals for a day)           score  22.9  [Pareto]
  5. Surge + 10 escalation beds on the ward        score  14.9

  - Choosing Surge + 4 extra ED bays over Surge + 2 extra ICU beds means accepting worse boarding time (140 vs 16.94).
  - Surge + 10 escalation beds on the ward is dominated by Surge + faster discharges (discharge lounge): ...
  - Compared with Flu surge (+60% arrivals for a day), Surge + 4 extra ED bays improves mean wait 1.578 → 0.6; left before treatment 17 → 0.
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
Scenario                        Availability  Downtime  Degraded time  Affected components  Recovery time  Intervention cost  Peak utilisation
Baseline (no incidents)         100.0%        0         0              0                    -              0                  65.0%
DB fails, no intervention       66.7%         10        0              3                    12             0                  65.0%
DB fails + cache fallback       100.0%        0         10             3                    12             50                 65.0%
DB fails + read replica         100.0%        0         0              1                    10             300                65.0%
DB fails + fast restore at t=8  90.0%         3         0              3                    5              0                  65.0%
2x traffic spike on gateway     100.0%        0         5              1                    5              0                  120.0%
Flaky week (probabilistic)      100.0%        0         6              3                    7              0                  65.0%

Monte Carlo: 1000 runs per scenario (model estimates, not predictions)

Scenario                                        Mean down  p50  p95  Max  P(down>0)  Mean avail.
DB fails, no intervention (deterministic)       10.00      10   10   10   100.0%     66.7%
DB fails + fast restore at t=8 (deterministic)  3.00       3    3    3    100.0%     90.0%
Flaky week (probabilistic)                      3.92       0    14   14   44.9%      86.9%
```

The last block shows why Monte Carlo matters: the flaky scenario's single run looks perfect,
but over 1,000 runs nearly half have downtime.

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
| POST / GET | `/scenarios/{id}/montecarlo` | run `{runs, until, base_seed?}` seeded runs and store the summary / list batches |
| GET | `/montecarlo/{id}` | one stored Monte Carlo summary (aggregates + per-run downtime) |
| GET | `/domains`, `/domains/{name}` | domain catalogs: entity, relationship, event and decision types, metrics, assumptions |
| GET / PUT | `/systems/{id}/objectives` | the decision model (objectives with weights, constraints); empty PUT resets to defaults |
| POST | `/systems/{id}/evaluate` | simulate scenarios (`runs` > 1 for Monte Carlo) and score, rank and explain them |
| POST | `/scenarios/{id}/sensitivity` | which inputs move a metric the most (each input -/+ `delta`) |
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
metrics, snapshots and timelines), `simulation_events` (causally linked log),
`monte_carlo_runs` (JSONB summary of a batch: aggregates and one downtime per run,
not 1,000 full logs; any single run can be reproduced from `base_seed + i`).
The schema is managed by Alembic migrations (`backend/app/database/migrations/`), applied
automatically when the API starts, so an existing database is upgraded in place.

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
    montecarlo.py  run_monte_carlo: N seeded runs -> mean / p50 / p95 / max, event frequency
  domains/
    base.py        DomainRules contract: intrinsic_status + effective_status
    infrastructure/rules.py   software-infrastructure propagation rules
    registry.py    domain name -> rules
  config.py        load an experiment JSON file
  cli.py           command-line runner
examples/ecommerce.json   the reference system with 7 scenarios (one probabilistic)
benchmarks/run_benchmarks.py   synthetic-graph benchmarks + cProfile (charts in docs/benchmarks/)
docs/architecture.md      how the layers, engine and data fit together

frontend/src/
  api/             typed API client + types mirroring backend schemas
  pages/           Projects, Design, Scenarios, Run (playback), Compare
  components/      graph node/edge rendering, inspectors, scenario forms, Monte Carlo panel
  lib/             pure logic with unit tests: layout, timeline, presets, histogram
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

Optional modelling, off unless you add the data: a dependency's `load_share`
passes that share of the caller's extra load downstream; component `latency`
gives end-to-end latency metrics (and `sla_breach_time` with a `latency_sla`
system parameter); `capacity` gives peak utilisation; `cost_per_time` gives
running and total cost.

### Scenarios and branching

A scenario has a `parent`. It inherits the parent's events and interventions,
can add or override them by id, and can drop events with `remove_events`.
Each run deep-copies the base system, applies interventions to the copy, and
runs on that copy, so branches never affect each other.

### Monte Carlo

A single run answers "what happens with this seed?". With probabilistic events that can
be lucky or unlucky, so `run_monte_carlo` runs the scenario N times with seeds
`base_seed, base_seed + 1, …` (base seed defaults to the scenario's seed, so run 0 equals
the normal single run). It reports mean, p50, p95 and max downtime, the fraction of runs
with any downtime, mean availability, and how often each event occurred. The same base
seed always gives the same aggregates. Percentiles use linear interpolation (numpy's default).
The UI labels all of these as **model estimates**.

## Domains in detail

**Software infrastructure.** Components depend on each other (`requires`, `optional`, `fallback`,
with groups for replicas and propagation delays). Failures, latency and overload spread to dependents,
event by event. Optional data adds load flow (`load_share`), end-to-end latency, an SLA, utilisation and
running cost. Metrics: availability, downtime, degraded time, affected components, recovery time, costs,
latency.

**Hospital operations.** A discrete-event queueing model. Patients arrive at random (Poisson), each unit
has beds/staff and a random treatment time, and routes carry the share of patients who go on next.
When the next unit is full, a patient can keep their current bed (*boarding*), which is how a full ICU
makes the emergency department crowded. Patients who wait longer than a unit's limit leave before
treatment. Each patient uses the same random numbers in every branch, so differences come from the
decisions. Metrics: mean and 95th-percentile wait, patients who left, discharges, length of stay,
boarding time, peak queue, bottleneck utilisation, crowded time, staffing and total cost.

**Cold-chain logistics.** Stores sell to random hourly demand and reorder at a reorder point; orders
come from whichever site can deliver fastest over open routes (Dijkstra), so a road closure reroutes
stock. Power outages beyond backup power and refrigeration failures on routes add exposure time; units
over the tolerance you set are discarded. Metrics: fill rate, lost sales, stockout time, units
discarded, exposure, on-time deliveries, delivery time, transport / holding / discard / total cost.

Each domain publishes a catalog (`GET /api/domains`) with its building blocks, events, decisions,
metrics (and whether lower or higher is better) and assumptions; the whole frontend is built from it.

## Decisions

On the **Futures** tab (or `POST /api/systems/{id}/evaluate`, or `--evaluate` in the CLI):

1. **Objectives** are metrics with weights; their direction comes from the catalog. **Limits** are hard
   constraints such as "fill rate ≥ 97%", optionally "in at least 90% of runs".
2. Every future is simulated (once with its seed, or N times) and each objective is rescaled across the
   futures (best = 1, worst = 0). The weighted average is the score; futures that break a limit rank last.
3. The **Pareto set** is the futures no other future beats on every objective. **Robustness** checks
   whether halving or doubling any single weight changes the winner.
4. **Insights** are sentences generated from those numbers: recommendation, trade-off, dominated futures,
   broken limits, robustness, improvement over the starting situation, tail risk and the main risk driver.
5. **Sensitivity** lowers and raises every numeric input by 20% (same random numbers) and ranks the inputs
   by how much they move a metric.

## Deploying

See [docs/DEPLOY.md](docs/DEPLOY.md). In short: the Docker image serves the API and the built frontend
from one process, reads `PORT` and `DATABASE_URL`, and migrates the database on startup. `render.yaml`
deploys the app and a PostgreSQL database on Render in a few clicks.

## Benchmarks

`python benchmarks/run_benchmarks.py` times the engine on synthetic graphs. In every case one
outage reaches every component (the worst case for propagation). Timings below are from one
Linux machine on Python 3.13; yours will differ, but the shape should not.

| Graph | 10 | 100 | 1,000 | 10,000 components |
|---|---|---|---|---|
| chain | 0.1 ms | 0.9 ms | 9.4 ms | 103 ms |
| tree (all share one root) | 0.1 ms | 0.9 ms | 10 ms | 122 ms |
| random DAG (~3 edges/node) | 0.2 ms | 2.9 ms | 33 ms | 557 ms |

| | |
|---|---|
| ![](docs/benchmarks/runtime_vs_nodes.png) | ![](docs/benchmarks/runtime_vs_events.png) |
| ![](docs/benchmarks/runtime_vs_branches.png) | ![](docs/benchmarks/runtime_vs_montecarlo.png) |

What the numbers say:

- **Runtime grows roughly linearly with graph size** (slope ≈ 1 on the log-log chart). The DAG is
  3–5× slower than a chain: it has about 3× the edges, so each status change re-evaluates
  about 3× as many dependents, and each evaluation has more dependencies to combine.
- **Event count is not what costs time; status changes are.** 1,000 overlapping failures on a
  1,000-node graph ran *faster* than 100, because most components were already failed and did
  not change again.
- **Branches cost the same each** (~49 ms on a 1,000-node DAG), so comparing 64 decisions is 64×
  one run. Monte Carlo is the same: about 3.7 ms per run on a 100-node graph.
- **The profile** (`benchmarks/results/profile.txt`) shows most time in
  `InfrastructureRules.effective_status`, i.e. combining dependency statuses, not in the queue.
  That is where an optimisation would start (for example caching group results per component).
- **The domain examples** (`python benchmarks/domains.py`): one run of the e-commerce example takes
  0.3 ms, the hospital example (72 hours, ~500 patients) about 18 ms and the cold-chain example
  (one week) about 9 ms; 100 Monte Carlo runs take 0.03 s, 1.6 s and 0.8 s. One evaluation or
  sensitivity request is capped at 10,000 simulations.

## Assumptions and limitations

- Branchpoint is a simulation based on user-defined rules. It is not a
  production reliability predictor.
- Load flows downstream only along dependencies with a `load_share`, instantly, and failed
  callers still forward it. Latency is a sum along the call path; queueing delay is not modelled.
- Decision scores are relative to the futures being compared, and depend on the weights you
  choose; the evaluation reports when a different weighting would change the winner.
- A delayed re-evaluation reads the dependency's status when it runs, so
  blips shorter than a propagation delay can be absorbed.
- Circular hard dependencies deadlock once both sides fail (the CLI warns
  about cycles).
- Monte Carlo results are estimates from the same rule-based model; they are only as good as
  the probabilities you enter. Runs are sequential (no parallelism), so 1,000 runs on a large
  graph takes seconds.
- Hospital: first-come-first-served queues without urgency levels; exponential treatment times;
  fixed routing shares. It is an operational planning toy, not clinical decision support.
- Cold chain: demand is checked hourly and unmet demand is lost; a shipment keeps the route it left on;
  exposure is a simple time count against your tolerance, not a product-safety model.
- There is no authentication; anyone who can open a deployed instance can edit it.
- The Docker image is built and smoke-tested in CI, but has not been run on Render by me (it needs
  your account).
- The frontend has unit tests for `lib/` and an end-to-end script, but no component tests.

## Roadmap

The 10-week single-domain plan is complete, and so is the multi-domain plan in
[docs/ROADMAP.md](docs/ROADMAP.md): a shared kernel and domain catalogs, the decision layer, the
futures dashboard, hospital and cold-chain domains, hardening and deployment configuration. Ideas for
later: urgency levels in the hospital model, back-orders and shelf life in the cold chain, parallel
Monte Carlo, user accounts, and a guided tutorial.
