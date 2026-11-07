"""Bring any database up to the latest schema with Alembic.

Called on startup. Three cases:

1. Empty database: every migration runs, starting from the baseline.
2. Database created before migrations existed (by ``create_all``, weeks
   1-10): it has the tables but no ``alembic_version`` row. Its schema is
   exactly the baseline (revision 0001), so we *stamp* it as 0001 and then
   upgrade. Existing data is kept.
3. Already migrated: only newer migrations run (often none).

New migrations go in ``migrations/versions`` (see ``backend/alembic.ini``).
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
BASELINE = "0001"


def _config(connection) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes["connection"] = connection
    return cfg


def migrate(engine: Engine, revision: str = "head") -> None:
    with engine.connect() as conn:
        if conn.dialect.name == "sqlite":
            # When SQLite has to rebuild a table to alter it, dropping the old
            # table would otherwise cascade-delete child rows. Must be set
            # outside a transaction, so do it before anything else.
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
        cfg = _config(conn)
        tables = set(inspect(conn).get_table_names())
        if "alembic_version" not in tables and "systems" in tables:
            command.stamp(cfg, BASELINE)
        command.upgrade(cfg, revision)
        conn.commit()
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.commit()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        if "alembic_version" not in inspect(conn).get_table_names():
            return None
        return conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
