"""Shared fixtures.

API tests use in-memory SQLite by default. To run them against PostgreSQL:
    TEST_DATABASE_URL=postgresql+psycopg://branchpoint:branchpoint@localhost:5432/branchpoint_test pytest
"""

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "ecommerce.json"


@pytest.fixture
def client():
    app = create_app(os.environ.get("TEST_DATABASE_URL", "sqlite://"))
    with TestClient(app) as c:
        yield c
    app.state.db.drop_tables()


@pytest.fixture
def example() -> dict:
    return json.loads(EXAMPLE.read_text())


@pytest.fixture
def imported(client, example) -> dict:
    """The e-commerce example imported via the API. Returns the ImportOut body."""
    r = client.post("/api/experiments/import", json=example)
    assert r.status_code == 201, r.text
    return r.json()
