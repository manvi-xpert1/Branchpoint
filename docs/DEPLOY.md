# Deploying Branchpoint

Branchpoint deploys as **one Docker container**: FastAPI serves the API under `/api` and the built
React app for every other path. The container:

- listens on the port in `PORT` (default 8000), which hosting services set for you;
- connects to the database in `DATABASE_URL` (a `postgres://…` URL from a host is accepted as is);
  without it, it uses a SQLite file inside the container, which is lost on every redeploy;
- applies database migrations on startup, so a new version upgrades the database by itself;
- answers `GET /health` with `{"status": "ok"}` for health checks.

## Option 1: Render (recommended, free tier)

The repository contains `render.yaml`, a *blueprint* that creates the web app and a PostgreSQL
database and connects them.

1. Push the repository to GitHub (see the README).
2. Sign in at <https://render.com> with your GitHub account.
3. **New → Blueprint**, pick the `Branchpoint` repository, and confirm. Render creates:
   - `branchpoint-db`: a free PostgreSQL database;
   - `branchpoint`: a web service built from the `Dockerfile`, with `DATABASE_URL` set from the database.
4. Wait for the first build (about 5 minutes: it builds the frontend, then the Python image).
5. Open the URL Render shows (`https://branchpoint-xxxx.onrender.com`). Click an example on the landing
   page to check that simulations run.

Things to know about the free tier:

- The web service **sleeps after 15 minutes without visitors**; the first request afterwards takes
  about a minute. Open the link a minute before you show it to someone.
- Free PostgreSQL databases **expire after 30 days** (Render emails you first). You can create a new
  one and redeploy: the app migrates the empty database on startup.
- Every push to `main` redeploys automatically (`autoDeploy: true`).

## Option 2: any Docker host (Railway, Fly.io, a VPS)

```bash
docker build -t branchpoint .
docker run -p 8000:8000 -e DATABASE_URL=postgresql+psycopg://user:pass@host:5432/branchpoint branchpoint
```

- **Railway:** New Project → Deploy from GitHub repo (it finds the Dockerfile) → add a PostgreSQL
  plugin → set the app's `DATABASE_URL` variable to the plugin's `DATABASE_URL`.
- **Fly.io:** `fly launch` (it detects the Dockerfile; choose to create a Postgres cluster when asked)
  then `fly deploy`. Fly sets `DATABASE_URL` when you attach the database.

## Option 3: locally with Docker Compose

```bash
docker compose up --build
```

starts PostgreSQL and the app on <http://localhost:8000>.

## Checking a deployment

```bash
curl https://<your-app>/health                 # {"status":"ok"}
curl https://<your-app>/api/domains | head     # the three domain catalogs
```

The API documentation is at `https://<your-app>/docs`.

## Before sharing a public link

- There is **no login**: anyone with the link can create, edit and delete systems. For a portfolio
  demo that is usually fine. Everything can be recreated from the examples.
- Requests are capped (10,000 simulations per evaluation or sensitivity request, 10,000 Monte Carlo
  runs), so one visitor cannot keep the server busy for long, but a free instance is small: expect a
  hospital Monte Carlo of 500 runs per future to take around a minute.
- `CORS_ORIGINS` only matters if you host the frontend somewhere else; with the single container the
  frontend and API share one origin.

## What CI checks

`.github/workflows/ci.yml` runs on every push: backend tests on SQLite and PostgreSQL 16, the
TypeScript check, frontend unit tests and production build, and a Docker build that starts the image
and checks `/health`, `/api/domains` and the home page.
