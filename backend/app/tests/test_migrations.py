"""Schema migrations keep existing data.

Simulates a database made before migrations existed (weeks 1-10): it has
the baseline tables but no alembic_version table. Starting the app must
upgrade it in place, keeping every row.
"""

import json
import os

import pytest
from sqlalchemy import inspect

from app.database.migrate import current_revision, migrate
from app.database.session import make_engine


@pytest.fixture
def engine():
    url = os.environ.get("TEST_DATABASE_URL", "sqlite://")
    eng = make_engine(url)
    yield eng
    with eng.begin() as conn:  # leave a shared Postgres test database empty
        for table in ["simulation_events", "monte_carlo_runs", "simulation_runs", "interventions",
                      "scenario_events", "scenarios", "dependencies", "components", "systems",
                      "alembic_version"]:
            conn.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")


def make_pre_migration_database(engine) -> None:
    """Baseline tables with data, and no record of any migration."""
    migrate(engine, "0001")
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE alembic_version")
        conn.exec_driver_sql(
            "INSERT INTO systems (id, name, domain, description, created_at, updated_at) "
            "VALUES ('s1', 'Shop', 'software_infrastructure', '', '2026-01-01', '2026-01-01')"
        )
        for i, key in enumerate(["api", "db"]):
            conn.exec_driver_sql(
                "INSERT INTO components (system_id, key, name, type, entry_point, attributes, position) "
                f"VALUES ('s1', '{key}', '{key}', 'service', {'true' if i == 0 else 'false'}, "
                f"'{json.dumps({'capacity': 100})}', {i})"
            )
        conn.exec_driver_sql(
            "INSERT INTO dependencies (system_id, key, source_key, target_key, dependency_type, "
            "propagation_delay, position) VALUES ('s1', 'api->db', 'api', 'db', 'requires', 1.0, 0)"
        )


def test_empty_database_is_built_from_the_migrations(engine):
    migrate(engine)
    assert current_revision(engine) == "0003"
    columns = {c["name"] for c in inspect(engine).get_columns("dependencies")}
    assert "attributes" in columns


def test_pre_migration_database_is_upgraded_without_losing_data(engine):
    make_pre_migration_database(engine)
    assert current_revision(engine) is None

    migrate(engine)

    assert current_revision(engine) == "0003"
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM components").scalar() == 2
        row = conn.exec_driver_sql(
            "SELECT propagation_delay, attributes FROM dependencies WHERE key = 'api->db'"
        ).one()
        params, objectives = conn.exec_driver_sql(
            "SELECT parameters, objectives FROM systems WHERE id = 's1'").one()
    assert row[0] == 1.0
    # new JSON columns are filled with an empty object for existing rows
    assert row[1] in ({}, "{}") and params in ({}, "{}") and objectives in ({}, "{}")


def test_migrating_twice_is_harmless(engine):
    migrate(engine)
    migrate(engine)
    assert current_revision(engine) == "0003"


def test_hosting_style_database_urls_are_accepted():
    from app.database.session import normalize_url

    assert normalize_url("postgres://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert normalize_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_url("postgresql+psycopg://u@h/db") == "postgresql+psycopg://u@h/db"
    assert normalize_url("sqlite:///x.db") == "sqlite:///x.db"
