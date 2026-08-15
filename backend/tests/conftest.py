"""Shared fixtures.

Every fixture here exists to keep the suite from touching anything real: no
Groq completions are billed, and fares.db is never opened.
"""

import json
import os
import sqlite3
import sys
import types
from pathlib import Path

import pytest

# main.py sits one level up and imports its siblings by bare name ("database"),
# so the backend directory has to be importable as-is.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The Groq client refuses to construct without a key, and importing main builds
# one at module level. The value is never used — every test stubs the client.
os.environ.setdefault("GROQ_API_KEY", "test-key-never-used")

import main  # noqa: E402


def _completion(content: str):
    message = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(choices=[choice])


def _stub_groq(create):
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
    )


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Rate-limit buckets are module-level, so they leak between tests."""
    main.rate_limit_buckets.clear()
    yield
    main.rate_limit_buckets.clear()


@pytest.fixture
def groq_accepts(monkeypatch):
    """Stub Groq to approve every fare. Returns the list of calls made."""
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return _completion(json.dumps({"is_valid": True, "reason": "looks fair"}))

    monkeypatch.setattr(main, "groq_client", _stub_groq(create))
    return calls


@pytest.fixture
def groq_rejects(monkeypatch):
    """Stub Groq to flag every fare as fake."""

    def create(**kwargs):
        return _completion(json.dumps({"is_valid": False, "reason": "clearly spam"}))

    monkeypatch.setattr(main, "groq_client", _stub_groq(create))


@pytest.fixture
def groq_unavailable(monkeypatch):
    """Stub Groq to fail the way a bad key or an outage would."""

    def create(**kwargs):
        raise RuntimeError("Invalid API Key sk-secret-abc123 for account groq-prod-42")

    monkeypatch.setattr(main, "groq_client", _stub_groq(create))


@pytest.fixture
def memory_db(monkeypatch):
    """Redirect the app at an in-memory database."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE fare_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            distance_km REAL NOT NULL,
            fare_amount REAL NOT NULL,
            route_type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    class KeepAlive:
        """The endpoint closes its connection per request; the DB must survive."""

        def cursor(self):
            return conn.cursor()

        def commit(self):
            conn.commit()

        def close(self):
            pass

    monkeypatch.setattr(main, "get_connection", lambda: KeepAlive())
    monkeypatch.setattr(main, "init_db", lambda: None)

    yield conn
    conn.close()


@pytest.fixture
def client(memory_db, groq_accepts):
    from fastapi.testclient import TestClient

    with TestClient(main.app) as test_client:
        yield test_client
