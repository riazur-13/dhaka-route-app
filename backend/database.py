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
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

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
        # Added after the table already had rows in production, so it arrives as
        # an ALTER rather than as a column in the CREATE above. Kept in one
        # place rather than both: a column defined twice is a column whose two
        # definitions drift.
        #
        # Nothing reads submitted_by yet. It is captured now because it cannot
        # be recovered later — once a fare is in the table, whether a passenger
        # or a driver typed it is gone, and the two have opposite incentives.
        # The NOT NULL DEFAULT keeps every existing row valid, and 'unknown' is
        # an honest label for rows submitted before anyone was asked.
        cursor.execute(
            """
            ALTER TABLE fare_submissions
            ADD COLUMN IF NOT EXISTS submitted_by TEXT NOT NULL DEFAULT 'unknown'
            CHECK (submitted_by IN ('passenger', 'driver', 'unknown'))
            """
        )
        # NUMERIC rather than DOUBLE PRECISION because these two columns are a
        # lookup key, not a measurement, and a key is only useful if `=` is
        # exact. Binary floating point stores 23.8103 as the nearest value it
        # can represent, which is close enough to draw a map with and not close
        # enough to match a row by.
        #
        # A NULL name is a cached *failure* — see cache_place_failure. One
        # nullable column instead of a separate is_negative flag, because two
        # columns describing the same fact can disagree and one cannot.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS geocode_cache (
                lat NUMERIC(8, 4) NOT NULL,
                lng NUMERIC(8, 4) NOT NULL,
                name TEXT,
                expires_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (lat, lng)
            )
            """
        )


# Roughly 11 metres at Dhaka's latitude — finer than anyone can aim a click, and
# coarse enough that two taps on the same doorway share a row.
COORDINATE_QUANTUM = Decimal("0.0001")

# A road does not get renamed twice in a month, so a name is worth keeping for a
# long time. A block or an outage is worth remembering only long enough to stop
# an impatient user's repeated clicks from becoming repeated outbound requests —
# short enough that service coming back is noticed within one coffee break.
GEOCODE_SUCCESS_TTL = timedelta(days=30)
GEOCODE_FAILURE_TTL = timedelta(minutes=5)


class CachedPlace(NamedTuple):
    """A cache hit.

    The wrapper exists so that a hit is distinguishable from a miss: the lookup
    returns None when it found nothing, and a CachedPlace when it found
    something — where `name` being None is itself the finding, meaning the last
    attempt at these coordinates failed upstream.
    """

    name: str | None


def round_coordinate(value: float) -> Decimal:
    """Snap a coordinate to the cache's grid.

    Via str() because Decimal(23.8103) would faithfully preserve the float's
    error and Decimal("23.8103") does not. ROUND_HALF_UP rather than Python's
    default banker's rounding, purely so the behaviour at a midpoint is the one
    a reader expects.
    """
    return Decimal(str(value)).quantize(COORDINATE_QUANTUM, rounding=ROUND_HALF_UP)


def lookup_place_name(lat: float, lng: float) -> CachedPlace | None:
    """Return the cached entry for these coordinates, or None if there is none.

    Expiry is evaluated by Postgres against its own clock, the same clock the
    writes below stamp expires_at with, so a skewed application server cannot
    make an entry immortal or stillborn.
    """
    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT name FROM geocode_cache
            WHERE lat = %s AND lng = %s AND expires_at > NOW()
            """,
            (round_coordinate(lat), round_coordinate(lng)),
        )
        row = cursor.fetchone()

    return None if row is None else CachedPlace(name=row[0])


def _write_cache_entry(lat: float, lng: float, name: str | None, ttl: timedelta) -> None:
    """Upsert one entry. The key is the grid square, so re-writes replace."""
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO geocode_cache (lat, lng, name, expires_at)
            VALUES (%s, %s, %s, NOW() + %s)
            ON CONFLICT (lat, lng) DO UPDATE
            SET name = EXCLUDED.name, expires_at = EXCLUDED.expires_at
            """,
            (round_coordinate(lat), round_coordinate(lng), name, ttl),
        )


def cache_place_name(lat: float, lng: float, name: str) -> None:
    """Remember a name Nominatim gave us."""
    _write_cache_entry(lat, lng, name, GEOCODE_SUCCESS_TTL)


def cache_place_failure(lat: float, lng: float) -> None:
    """Remember that Nominatim could not answer for these coordinates.

    This is the entry that matters while the datacenter IP is blocked: without
    it, a user clicking the same blocked spot five times sends five requests to
    a service that has already refused us five times.
    """
    _write_cache_entry(lat, lng, None, GEOCODE_FAILURE_TTL)
