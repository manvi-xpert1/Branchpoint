"""FastAPI application.

    cd backend
    uvicorn app.main:app --reload
    # then open http://localhost:8000/docs
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .api import decisions, domains, scenarios, simulations, systems
from .database import Database
from .services.errors import ServiceError


def create_app(database_url: str | None = None) -> FastAPI:
    db = Database(database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Applies any pending Alembic migrations (creates the tables on a new database).
        db.create_tables()
        yield
        db.engine.dispose()

    app = FastAPI(
        title="Branchpoint API",
        version="0.3.0",
        description="Explore alternative futures and make better decisions: model a system, branch "
                    "scenarios, simulate them, and score the outcomes against your objectives.",
        lifespan=lifespan,
    )
    app.state.db = db

    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    for module in (domains, systems, scenarios, simulations, decisions):
        app.include_router(module.router, prefix="/api")
    _serve_frontend(app)
    return app


def _serve_frontend(app: FastAPI) -> None:
    """Serve the built React app (frontend/dist) if it exists.

    In development the Vite dev server serves the frontend instead.
    Unknown paths return index.html so client-side routes work on reload.
    """
    default = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    dist = Path(os.environ.get("FRONTEND_DIR", default)).resolve()
    if not (dist / "index.html").is_file():
        return

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist):
            return FileResponse(file)
        return FileResponse(dist / "index.html")


app = create_app()
