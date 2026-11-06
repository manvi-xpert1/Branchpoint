"""FastAPI application.

    cd backend
    uvicorn app.main:app --reload
    # then open http://localhost:8000/docs
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import scenarios, simulations, systems
from .database import Database
from .services.errors import ServiceError


def create_app(database_url: str | None = None) -> FastAPI:
    db = Database(database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Fine for V1. Switch to Alembic migrations once the schema settles.
        db.create_tables()
        yield
        db.engine.dispose()

    app = FastAPI(
        title="Branchpoint API",
        version="0.2.0",
        description="Model systems, inject failures, branch scenarios and compare outcomes.",
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

    for module in (systems, scenarios, simulations):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()
