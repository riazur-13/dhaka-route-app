"""One invariant: no endpoint may be `async def` unless it is on the allow-list.

`database.py` uses psycopg's *synchronous* ConnectionPool, so every query in
this project blocks the thread it runs on. FastAPI handles that correctly for a
plain `def` endpoint — it hands the function to a worker thread and the event
loop stays free. An `async def` endpoint runs *on* the event loop, so a blocking
query inside one stalls every other request in the process for the duration,
including requests that have nothing to do with the database.

Nothing about that failure is loud. There is no exception, no warning, and no
log line; the endpoint returns the right answer and the symptom shows up as
unrelated requests being mysteriously slow under load. That is why it is worth
a test rather than a comment: `async def` is a one-word change that looks like a
modernisation and behaves like a throughput regression.

This test is pure inspection — no database, no network, no TestClient — so it
runs even with TEST_DATABASE_URL unset.
"""

import inspect

import main
from fastapi.routing import APIRoute

# Endpoints permitted to be `async def`, and why each one is safe.
ASYNC_ALLOWED = {
    # Returns a literal. No database, no outbound call, nothing to block on —
    # the strongest entry on this list, and the only one that is safe by having
    # no body rather than by being careful about one. Async on purpose: a health
    # check earns its keep when the worker pool is saturated, which is precisely
    # when a `def` version would be stuck in the queue behind the saturation.
    "/health",
    # Awaits httpx against OSRM and touches the database not at all. There is
    # nothing here to block on except the network call it is already awaiting.
    "/route",
    # Same shape: one awaited httpx call to Nominatim, no database access. The
    # geocode cache is deliberately not on this path.
    "/search",
    # This one *does* reach Postgres, three times. It is allowed because every
    # one of those calls is wrapped in starlette's run_in_threadpool, which puts
    # the blocking work back on a worker thread. Remove that wrapper and this
    # entry stops being true — the allow-list is not a blanket exemption for the
    # path, it is a claim about how the path is written.
    "/reverse-geocode",
}


def test_no_unexpected_endpoint_is_async():
    """Every other endpoint must stay `def` so FastAPI threads it."""
    offenders = [
        route.path
        for route in main.app.routes
        if isinstance(route, APIRoute)
        and inspect.iscoroutinefunction(route.endpoint)
        and route.path not in ASYNC_ALLOWED
    ]

    assert offenders == [], (
        f"These endpoints are declared `async def`: {offenders}. "
        "They reach Postgres through the synchronous psycopg ConnectionPool in "
        "database.py (and, for the fare endpoints, the synchronous Groq client), "
        "both of which block the thread they run on. Declared `async def` they "
        "run on the event loop itself, so each blocking call freezes every other "
        "request in the process until it returns — a Groq completion can hold the "
        "loop for seconds. Nothing raises and nothing is logged when this "
        "happens; the endpoint still returns the correct response, and the only "
        "symptom is unrelated requests going slow under load. Either declare the "
        "endpoint `def` so FastAPI runs it in a worker thread, or wrap every "
        "blocking call in starlette.concurrency.run_in_threadpool and add the "
        "path to ASYNC_ALLOWED above with a note saying why it is safe."
    )
