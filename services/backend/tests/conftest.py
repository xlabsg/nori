import pytest
from fastapi.testclient import TestClient

from finance_agent.adapters.database import Database
from finance_agent.entrypoints.api import create_app
from finance_agent.modules.tasks.service import TaskService
from finance_agent.settings import ROOT, Settings


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate(ROOT / "services/backend/migrations")
    return db


@pytest.fixture
def tasks(database):
    return TaskService(database)


@pytest.fixture
def client(database):
    settings = Settings(database.path, {"test-token-a": "a", "test-token-b": "b"})
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def input_data():
    return {
        "currency": "USD",
        "observed_at": "2026-10-01T00:00:00Z",
        "source": "synthetic-fixture",
        "opening_equity": "10000",
        "closing_equity": "12500",
        "cash_flows": [{"kind": "deposit", "amount": "2000", "external": True}],
    }
