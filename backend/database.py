"""Postgres access for the crowdsourced fare store.

This was SQLite (a local fares.db file) until the move to Neon. The file-backed
version lost every submission on each Render deploy, because the free tier gives
the service a fresh disk on every restart — the fares users contributed only ever
survived until the next push.

Connections come from a pool rather than being opened per request. The database
lives in another region behind TLS, so a fresh connect costs a round trip plus a
handshake on every single query; the pool pays that once and hands the warm
connection back out.

The pool is built lazily instead of at import time on purpose: build.sh imports
main.py during the Render build to catch syntax errors, and that build step has no
database credentials and no business talking to Neon.
"""

import threading
from contextlib import contextmanager

from psycopg_pool import ConnectionPool

from config import get_env

# Neon's pooler drops idle connections, so a pooled connection can be dead by the
# time we hand it out. `check` makes the pool test each one on checkout and
# transparently replace it, which turns "server closed the connection
# unexpectedly" on the first request after a quiet period into a non-event.
POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 5
POOL_TIMEOUT_SECONDS = 10.0

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    """Return the process-wide connection pool, creating it on first use."""
    global _pool

    if _pool is not None:
        return _pool

    with _pool_lock:
        # Another thread may have built it while we waited for the lock.
        if _pool is None:
            # Read here rather than at import so the pool stays lazy, and read
            # through get_env so a newline picked up from the Render dashboard
            # or a .env file cannot reach the connection string.
            database_url = get_env("DATABASE_URL")
            if not database_url:
                raise RuntimeError(
                    "DATABASE_URL is not set. Point it at your Postgres instance, "
                    "e.g. postgresql://user:password@host/dbname?sslmode=require"
                )

            _pool = ConnectionPool(
                conninfo=database_url,
                min_size=POOL_MIN_SIZE,
                max_size=POOL_MAX_SIZE,
                timeout=POOL_TIMEOUT_SECONDS,
                check=ConnectionPool.check_connection,
                open=True,
            )

    return _pool


def close_pool() -> None:
    """Close every pooled connection. Called on application shutdown."""
    global _pool

    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def db_cursor():
    """Yield a cursor on a pooled connection.

    The surrounding transaction commits when the block exits cleanly and rolls
    back if it raises, so callers never commit by hand. That is what keeps a
    rejected fare from being half-written: if validation raises inside the block,
    nothing lands.
    """
    with get_pool().connection() as conn:
        with conn.cursor() as cursor:
            yield cursor


def init_db() -> None:
    """Create the fare table and its index if they are not there yet."""
    with db_cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS fare_submissions (
                id BIGSERIAL PRIMARY KEY,
                distance_km DOUBLE PRECISION NOT NULL,
                fare_amount DOUBLE PRECISION NOT NULL,
                route_type TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        # Both read paths filter on route_type and a distance window, and there is
        # no other access pattern. Without this every average is a sequential scan.
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS fare_submissions_route_distance_idx
            ON fare_submissions (route_type, distance_km)
            """
        )
