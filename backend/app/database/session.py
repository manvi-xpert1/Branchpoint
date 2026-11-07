"""Database engine and session setup.

DATABASE_URL picks the database:
  * PostgreSQL (used by docker-compose):
        postgresql+psycopg://branchpoint:branchpoint@localhost:5432/branchpoint
  * Unset: a local SQLite file, so the API runs with zero setup.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

DEFAULT_URL = "sqlite:///./branchpoint.db"


def normalize_url(url: str) -> str:
    """Hosting services hand out ``postgres://...`` URLs; SQLAlchemy needs the psycopg 3 driver named."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(url: str | None = None) -> Engine:
    url = normalize_url(url or os.environ.get("DATABASE_URL", DEFAULT_URL))
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool  # one shared in-memory DB
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite ignores foreign keys unless asked
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    return create_engine(url, pool_pre_ping=True)


class Database:
    def __init__(self, url: str | None = None) -> None:
        self.engine = make_engine(url)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_tables(self) -> None:
        """Create or upgrade the schema by running the Alembic migrations."""
        from .migrate import migrate

        migrate(self.engine)

    def drop_tables(self) -> None:
        from .tables import Base

        Base.metadata.drop_all(self.engine)
        with self.engine.begin() as conn:  # so the next create_tables starts from scratch
            conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")

    def session(self) -> Iterator[Session]:
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()
