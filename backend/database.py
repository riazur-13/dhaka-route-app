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

import json
import re
import threading
import unicodedata
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
        # Same reasoning as submitted_by, and the same impossibility: nobody can
        # look at a stored fare later and tell whether it was paid to a pedal
        # rickshaw or a battery one. Only the passenger knew, and only at the
        # moment they typed it.
        #
        # This one is not merely lost information, it is actively wrong to
        # average over. Battery rickshaws are priced below pedal ones on
        # purpose — the motor does the work the puller's legs would — so a
        # crowd average mixing the two drags the pedal recommendation down
        # toward the battery rate, which is the exact direction the labour
        # floor in config.py exists to prevent. Every row written before this
        # column existed is 'unknown' and is therefore excluded from both
        # vehicle's averages rather than being guessed at.
        cursor.execute(
            """
            ALTER TABLE fare_submissions
            ADD COLUMN IF NOT EXISTS vehicle_type TEXT NOT NULL DEFAULT 'unknown'
            CHECK (vehicle_type IN ('pedal', 'battery', 'unknown'))
            """
        )
        # Equality columns first, the range column last. Postgres can only use
        # index columns up to and including the first inequality, so with
        # distance_km ahead of vehicle_type the vehicle filter would have to be
        # rechecked against the heap on every candidate row.
        #
        # The older (route_type, distance_km) index is deliberately left alone.
        # It still serves /fares/average, which does not filter on vehicle, and
        # dropping an index is a decision about a live table rather than a
        # side effect of adding a column.
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS fare_submissions_route_vehicle_distance_idx
            ON fare_submissions (route_type, vehicle_type, distance_km)
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
        # The forward direction of the same idea, and the one that makes
        # autocomplete legal to ship. Nominatim allows one request a second and
        # has blocked this service's IP range once already; a search firing as
        # the user types would walk straight back into that. Debouncing thins
        # one user's keystrokes, and this stops every user after the first from
        # asking again at all.
        #
        # results is JSONB rather than text because what is stored is already a
        # list of objects, and a NULL means the *upstream* failed — see
        # cache_search_failure. An empty list is a different thing entirely: a
        # real answer that nothing matched. One nullable column carries that
        # distinction, as with geocode_cache.name above, rather than a second
        # flag column that could contradict it.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS search_cache (
                query TEXT PRIMARY KEY,
                results JSONB,
                expires_at TIMESTAMPTZ NOT NULL
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


# Runs of any whitespace collapse to one space, so "new  market" and
# "new\tmarket" are the same cache key rather than two.
_WHITESPACE_RUN = re.compile(r"\s+")


def normalise_query(query: str) -> str:
    """Reduce a typed query to its cache key.

    The text counterpart of round_coordinate: both exist so that two inputs a
    user would call identical land on one row instead of two.

    NFC first, and that step is not decorative here. Bengali has more than one
    valid codepoint sequence for the same visible text — a vowel sign can be
    stored precomposed or as separate marks — so "ঢাকা" typed on two keyboards
    can differ byte for byte while looking the same to the person who typed it.
    Without normalising, each spelling would miss the other's cache entry and
    send its own request upstream.

    casefold rather than lower: lower() is written for English, casefold is the
    Unicode-wide form and is what handles scripts we have not thought about.
    """
    return _WHITESPACE_RUN.sub(" ", unicodedata.normalize("NFC", query)).strip().casefold()


class CachedSearch(NamedTuple):
    """A cache hit for a search query.

    Same shape of answer as CachedPlace: the lookup returns None for a miss and
    one of these for a hit, where `results` being None is itself the finding —
    the last attempt at this query failed upstream. An empty list means the
    search ran and matched nothing, which is a different fact with a different
    lifetime.
    """

    results: list[dict] | None


def lookup_search_results(query: str) -> CachedSearch | None:
    """Return the cached results for this query, or None if there are none.

    Expiry is evaluated by Postgres against its own clock, the same clock the
    writes stamp expires_at with, so a skewed application server cannot make an
    entry immortal or stillborn.
    """
    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT results FROM search_cache
            WHERE query = %s AND expires_at > NOW()
            """,
            (normalise_query(query),),
        )
        row = cursor.fetchone()

    return None if row is None else CachedSearch(results=row[0])


def _write_search_entry(query: str, results: list[dict] | None, ttl: timedelta) -> None:
    """Upsert one entry. The key is the normalised query, so re-writes replace."""
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO search_cache (query, results, expires_at)
            VALUES (%s, %s, NOW() + %s)
            ON CONFLICT (query) DO UPDATE
            SET results = EXCLUDED.results, expires_at = EXCLUDED.expires_at
            """,
            # json.dumps because psycopg adapts a Python list to a Postgres
            # array, not to JSONB, and these rows are objects rather than
            # scalars. None stays None and lands as SQL NULL.
            (
                normalise_query(query),
                json.dumps(results) if results is not None else None,
                ttl,
            ),
        )


def cache_search_results(query: str, results: list[dict]) -> None:
    """Remember what a search returned, including when it returned nothing.

    An empty list gets the same long lifetime as a full one, on purpose. Zero
    matches is a real answer from a service that replied successfully, not an
    outage — the same reasoning as caching Nominatim's "no address here" for
    open water. And it is the most valuable entry of the lot: a spelling that
    matches nothing is the one people retype, and without this each retype is
    another wasted request to a service that has already said no.

    The cost is staleness. A place added to OpenStreetMap tomorrow stays
    invisible here for up to the success TTL. That trade is deliberate.
    """
    _write_search_entry(query, results, GEOCODE_SUCCESS_TTL)


def cache_search_failure(query: str) -> None:
    """Remember that the search provider could not answer at all.

    The short TTL, mirroring cache_place_failure, because this says nothing
    about the query and everything about the provider — it should stop applying
    as soon as they are answering again.

    Autocomplete is why this matters more here than on the reverse path. While
    Nominatim is refusing us, every debounce from every user typing at once
    would otherwise become a fresh doomed request, which is how the block
    happened in the first place.
    """
    _write_search_entry(query, None, GEOCODE_FAILURE_TTL)
