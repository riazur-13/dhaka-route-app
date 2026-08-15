"""The /fares submission path: throttling, rejection messages, error hygiene."""

import main

VALID_FARE = {"distance_km": 3.0, "fare_amount": 80.0, "route_type": "rickshaw"}


def submit(client, ip, payload=None):
    return client.post(
        "/fares",
        json=payload or VALID_FARE,
        headers={"x-forwarded-for": ip},
    )


def test_backend_imports_with_all_routes_registered():
    """Mirrors the check in build.sh, which guards the deploy."""
    paths = {route.path for route in main.app.routes if hasattr(route, "path")}
    assert {"/route", "/fares", "/fares/average", "/search"} <= paths


def test_submissions_up_to_the_per_client_limit_succeed(client):
    for _ in range(main.PER_CLIENT_MAX_SUBMISSIONS):
        assert submit(client, "203.0.113.7").status_code == 200


def test_per_client_limit_blocks_the_next_submission(client):
    for _ in range(main.PER_CLIENT_MAX_SUBMISSIONS):
        submit(client, "203.0.113.7")

    response = submit(client, "203.0.113.7")

    assert response.status_code == 429
    assert response.headers.get("Retry-After")
    assert isinstance(response.json()["detail"], str)


def test_one_client_hitting_the_limit_does_not_block_another(client):
    for _ in range(main.PER_CLIENT_MAX_SUBMISSIONS + 2):
        submit(client, "203.0.113.7")

    assert submit(client, "198.51.100.4").status_code == 200


def test_global_cap_holds_when_the_client_key_is_spoofed(client, groq_accepts):
    """X-Forwarded-For is caller-supplied, so per-client alone is not a defense.

    An attacker rotating the header gets a fresh bucket every request. The
    global window is what actually bounds how much Groq quota can be burned.
    """
    accepted = 0
    blocked = False

    for i in range(main.GLOBAL_MAX_SUBMISSIONS * 3):
        response = submit(client, f"10.0.{i // 256}.{i % 256}")
        if response.status_code == 429:
            blocked = True
            break
        accepted += 1

    assert blocked, "rotating the client key bypassed the limiter entirely"
    assert accepted <= main.GLOBAL_MAX_SUBMISSIONS
    assert len(groq_accepts) <= main.GLOBAL_MAX_SUBMISSIONS


def test_throttled_requests_never_reach_groq(client, groq_accepts):
    for _ in range(main.PER_CLIENT_MAX_SUBMISSIONS + 5):
        submit(client, "203.0.113.7")

    assert len(groq_accepts) == main.PER_CLIENT_MAX_SUBMISSIONS


def test_rate_limit_buckets_do_not_grow_without_bound(client):
    for i in range(50):
        submit(client, f"192.0.2.{i}")

    assert len(main.rate_limit_buckets) <= main.MAX_TRACKED_CLIENTS + 1


def test_absurd_fare_is_rejected_with_a_readable_reason(client):
    response = client.post(
        "/fares",
        json={"distance_km": 2.0, "fare_amount": 5000.0, "route_type": "rickshaw"},
        headers={"x-forwarded-for": "203.0.113.99"},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    # The frontend renders this directly, so it has to be a string, not the
    # list-of-objects shape FastAPI uses for its own validation errors.
    assert isinstance(detail, str) and detail


def test_ai_rejection_reaches_the_client(client, groq_rejects):
    response = submit(client, "203.0.113.50")

    assert response.status_code == 400
    assert "clearly spam" in response.json()["detail"]


def test_accepted_fare_is_persisted(client, memory_db):
    assert submit(client, "203.0.113.60").status_code == 200

    rows = memory_db.execute("SELECT distance_km, fare_amount FROM fare_submissions").fetchall()
    assert rows == [(3.0, 80.0)]


def test_rejected_fare_is_not_persisted(client, memory_db, groq_rejects):
    submit(client, "203.0.113.61")

    count = memory_db.execute("SELECT COUNT(*) FROM fare_submissions").fetchone()[0]
    assert count == 0


def test_recommendation_failure_does_not_leak_internals(client, groq_unavailable):
    """str(e) used to be returned straight to the browser."""
    response = client.get(
        "/ai-fare-recommendation",
        params={"distance_km": 3, "route_type": "rickshaw", "area": "Gulshan"},
    )

    assert response.status_code == 200
    body = response.json()["recommendation"]
    for leaked in ("sk-secret", "groq-prod", "RuntimeError", "Invalid API Key", "Traceback"):
        assert leaked not in body
