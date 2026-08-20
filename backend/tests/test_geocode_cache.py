"""The reverse-geocode cache: what it stores, what it serves, and for how long.

The cache is not an optimisation here, it is the mitigation. Nominatim is
blocking the shared datacenter IP Render gives us, and no header fixes that —
the only thing that helps is asking them less often, and answering from what we
already know when they refuse.
"""

import database

DHAKA = {"lat": 23.8103, "lng": 90.4125}

NOMINATIM_ANSWER = {
    "address": {"road": "Kazi Nazrul Islam Avenue", "suburb": "Tejgaon"},
    "display_name": "Kazi Nazrul Islam Avenue, Tejgaon, Dhaka",
}


def get(client, lat=DHAKA["lat"], lng=DHAKA["lng"]):
    return client.get("/reverse-geocode", params={"lat": lat, "lng": lng})


def test_a_successful_lookup_is_written_through(client, upstream, geocode_cache):
    upstream.replies(status_code=200, json=NOMINATIM_ANSWER)

    assert get(client).json() == {"name": "Kazi Nazrul Islam Avenue"}
    assert geocode_cache.count() == 1


def test_a_second_request_is_served_without_calling_nominatim(client, upstream):
    upstream.replies(status_code=200, json=NOMINATIM_ANSWER)

    first = get(client)
    second = get(client)

    assert first.json() == second.json()
    assert len(upstream.requests) == 1


def test_clicks_inside_the_same_grid_square_share_one_entry(client, upstream, geocode_cache):
    """Four decimal places is about 11 metres — finer than anyone can aim."""
    upstream.replies(status_code=200, json=NOMINATIM_ANSWER)

    get(client, lat=23.81032, lng=90.41249)
    get(client, lat=23.81028, lng=90.41253)

    assert len(upstream.requests) == 1
    assert geocode_cache.count() == 1


def test_an_upstream_failure_is_cached_so_the_next_click_costs_nothing(client, upstream):
    """The behaviour that actually protects us while the IP block is in place."""
    upstream.replies(status_code=403, text="blocked")

    assert get(client).status_code == 502
    assert get(client).status_code == 502

    assert len(upstream.requests) == 1


def test_a_cached_failure_still_answers_502_rather_than_a_stale_name(client, upstream):
    upstream.replies(status_code=403, text="blocked")
    get(client)

    response = get(client)

    assert response.status_code == 502
    assert isinstance(response.json()["detail"], str)


def test_a_failure_is_remembered_for_minutes_and_a_name_for_weeks(client, upstream, geocode_cache):
    """Different lifetimes are the reason the column is expires_at, not created_at."""
    upstream.replies(status_code=403, text="blocked")
    get(client)
    failure_ttl = geocode_cache.seconds_until_expiry(**DHAKA)

    upstream.replies(status_code=200, json=NOMINATIM_ANSWER)
    get(client, lat=23.7806, lng=90.4193)
    success_ttl = geocode_cache.seconds_until_expiry(lat=23.7806, lng=90.4193)

    assert 0 < failure_ttl <= database.GEOCODE_FAILURE_TTL.total_seconds()
    assert success_ttl > database.GEOCODE_SUCCESS_TTL.total_seconds() - 60
    assert failure_ttl < success_ttl


def test_an_expired_failure_lets_the_next_request_try_again(client, upstream, geocode_cache):
    """A block lifting has to be noticed without a deploy."""
    upstream.replies(status_code=403, text="blocked")
    assert get(client).status_code == 502

    geocode_cache.expire(**DHAKA)
    upstream.replies(status_code=200, json=NOMINATIM_ANSWER)

    assert get(client).json() == {"name": "Kazi Nazrul Islam Avenue"}
    assert len(upstream.requests) == 2


def test_a_retry_overwrites_the_failed_entry_rather_than_adding_one(client, upstream, geocode_cache):
    """The key is the grid square, so the table is bounded by places, not time."""
    upstream.replies(status_code=403, text="blocked")
    get(client)
    geocode_cache.expire(**DHAKA)

    upstream.replies(status_code=200, json=NOMINATIM_ANSWER)
    get(client)

    assert geocode_cache.count() == 1


def test_nominatim_finding_nothing_is_an_answer_not_a_failure(client, upstream, geocode_cache):
    """Open water has no road. That is a real result and it keeps for 30 days."""
    upstream.replies(status_code=200, json={"error": "Unable to geocode"})

    response = get(client)

    assert response.status_code == 200
    assert response.json() == {"name": "23.8103, 90.4125"}
    assert geocode_cache.seconds_until_expiry(**DHAKA) > database.GEOCODE_FAILURE_TTL.total_seconds()


def test_the_cache_is_read_before_nominatim_is_ever_called(client, upstream):
    database.cache_place_name(DHAKA["lat"], DHAKA["lng"], "Mirpur Road")

    assert get(client).json() == {"name": "Mirpur Road"}
    assert upstream.requests == []


def test_rounding_is_exact_at_the_boundary():
    """Decimal, not float: a key is only a key if = is exact."""
    assert database.round_coordinate(23.81035) == database.round_coordinate(23.8104)
    assert str(database.round_coordinate(23.8103)) == "23.8103"
    assert str(database.round_coordinate(90.0)) == "90.0000"
