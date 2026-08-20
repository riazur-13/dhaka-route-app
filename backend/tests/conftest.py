"""Shared fixtures.

Every fixture here exists to keep the suite from touching anything real: no
Groq completions are billed, and the production database is never opened.

The database tests run against a real Postgres, not a stand-in. They used to run
against an in-memory SQLite, which stopped being worth anything the moment the
app moved to Postgres: the placeholder style (%s vs ?), the schema types, and
BIGSERIAL are exactly the things a migration gets wrong, and a SQLite double
would have accepted all three regardless.

Set TEST_DATABASE_URL to a throwaway database to run them. Locally that is:

    docker run --rm -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres --name fares-test postgres:17
    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres pytest

Deliberately a *separate* variable from DATABASE_URL: importing main runs
load_dotenv(), so DATABASE_URL is already populated with the live Neon
credentials by the time the fixtures run, and the fixture truncates the table it
is given.
"""

import json
import os
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

import database  # noqa: E402
import main  # noqa: E402
from config import get_env  # noqa: E402


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


class FareTable:
    """Read-side helper so tests can assert on what actually landed."""

    def query(self, sql: str, params: tuple = ()):
        with database.db_cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def count(self) -> int:
        return self.query("SELECT COUNT(*) FROM fare_submissions")[0][0]


@pytest.fixture(scope="session")
def test_database():
    """Point the app at the throwaway test database for the whole session.

    Session-scoped because tearing the pool down between tests meant paying for a
    fresh TLS handshake to a remote Postgres on every single one.
    """
    test_url = get_env("TEST_DATABASE_URL")
    if not test_url:
        message = (
            "TEST_DATABASE_URL is not set, so the database tests cannot run. "
            "See the module docstring in tests/conftest.py for the one-line "
            "docker command that provides one."
        )
        # A missing test database must never quietly shrink CI to a green run
        # over a handful of pure-arithmetic tests.
        if get_env("CI"):
            pytest.fail(message)
        pytest.skip(message)

    # importing main ran load_dotenv(), so DATABASE_URL currently holds the live
    # credentials. The pool caches whatever it read when it was first built, so
    # it has to be torn down before this override can take effect.
    patch = pytest.MonkeyPatch()
    patch.setenv("DATABASE_URL", test_url)
    database.close_pool()

    database.init_db()

    yield

    database.close_pool()
    patch.undo()


@pytest.fixture
def fare_db(test_database):
    """Empty the fare table, then hand back a reader for it."""
    with database.db_cursor() as cursor:
        cursor.execute("TRUNCATE fare_submissions RESTART IDENTITY")

    return FareTable()


@pytest.fixture
def client(fare_db, groq_accepts):
    from fastapi.testclient import TestClient

    with TestClient(main.app) as test_client:
        yield test_client
