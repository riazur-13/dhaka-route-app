"""The search cache: what makes autocomplete legal to point at Nominatim.

Nominatim allows one request per second, and this service's IP range has been
blocked by them once already. Search that fires as the user types multiplies
requests by keystrokes and by concurrent users; debouncing thins one person's
typing, and this stops everyone after the first from asking at all.

So these are not performance tests. They are the tests that say the feature is
allowed to ship.

The mirror of test_geocode_cache.py, deliberately — same table shape, same
TTLs, same nullable column carrying "the upstream failed" as distinct from "it
answered with nothing".
"""

import database
import main
import psycopg

NOMINATIM_ANSWER = [
    {
        "display_name": "Dhanmondi, Dhaka, Dhaka Metropolitan, Bangladesh",
        "lat": "23.7461",
        "lon": "90.3742",
    }
]


def search(client, query="Dhanmondi"):
    return client.get("/search", params={"query": query})


class TestASecondSearchCostsNothing:
    """The behaviour the whole feature depends on."""

    def test_a_repeated_query_makes_no_upstream_call(self, client, upstream):
        upstream.replies(status_code=200, json=NOMINATIM_ANSWER)

        first = search(client)
        second = search(client)

        assert first.json() == second.json()
        assert len(upstream.requests) == 1, "the second search went upstream"

    def test_the_tenth_search_still_makes_no_upstream_call(self, client, upstream):
        """Autocomplete means a lot of repeats, not just one."""
        upstream.replies(status_code=200, json=NOMINATIM_ANSWER)

        for _ in range(10):
            search(client)

        assert len(upstream.requests) == 1

    def test_the_cached_answer_is_the_parsed_shape_not_the_raw_body(
        self, client, upstream, search_cache
    ):
        """What keeps the provider swappable.

        The cache stores our {name, full_name, lat, lng} rather than
        Nominatim's display_name/lat/lon, so moving to Mapbox or LocationIQ
        changes the URL, the params and the field mapping in search_place() and
        touches nothing here.
        """
        upstream.replies(status_code=200, json=NOMINATIM_ANSWER)

        search(client)

        stored = search_cache.results_for("Dhanmondi")
        assert stored is not None
        assert set(stored[0]) == {"name", "full_name", "lat", "lng"}
        assert "display_name" not in stored[0]


class TestAnEmptyResultIsCachedToo:
    """The most valuable entry of the lot."""

    def test_nothing_found_is_remembered(self, client, upstream, search_cache):
        """"Barua" matches nothing because OpenStreetMap files it as "Borua".

        That is the spelling people retype, so without this each retype is
        another wasted request to a service that has already said no.
        """
        upstream.replies(status_code=200, json=[])

        assert search(client, "Barua").json() == {"results": []}

        assert search_cache.count() == 1
        assert search_cache.results_for("Barua") == []

    def test_a_repeated_empty_query_makes_no_upstream_call(self, client, upstream):
        upstream.replies(status_code=200, json=[])

        search(client, "Barua")
        search(client, "Barua")
        search(client, "Barua")

        assert len(upstream.requests) == 1

    def test_an_empty_result_is_kept_as_long_as_a_full_one(
        self, client, upstream, search_cache
    ):
        """Zero matches is a real answer, not an outage.

        Same reasoning already written down for Nominatim's "no address here"
        over open water: the service replied successfully, so it keeps the
        long TTL rather than the short failure one.
        """
        upstream.replies(status_code=200, json=[])
        search(client, "Barua")

        remaining = search_cache.seconds_until_expiry("Barua")

        assert remaining > database.GEOCODE_FAILURE_TTL.total_seconds()
        assert remaining > database.GEOCODE_SUCCESS_TTL.total_seconds() - 60


class TestAnUpstreamFailureIsCachedBriefly:
    """Short, because it says nothing about the query and everything about them."""

    def test_a_502_is_remembered(self, client, upstream, search_cache):
        upstream.replies(status_code=403, text="blocked")

        assert search(client).status_code == 502

        assert search_cache.count() == 1
        # NULL results is how a failure is stored, distinct from [].
        assert search_cache.results_for("Dhanmondi") is None

    def test_a_cached_failure_replays_without_asking_again(self, client, upstream):
        """While they are refusing us, every debounce would otherwise be a
        fresh doomed request — which is how the block happened."""
        upstream.replies(status_code=403, text="blocked")

        assert search(client).status_code == 502
        assert search(client).status_code == 502
        assert search(client).status_code == 502

        assert len(upstream.requests) == 1

    def test_a_failure_expires_far_sooner_than_an_answer(
        self, client, upstream, search_cache
    ):
        upstream.replies(status_code=403, text="blocked")
        search(client, "Gulshan")
        failure_ttl = search_cache.seconds_until_expiry("Gulshan")

        upstream.replies(status_code=200, json=NOMINATIM_ANSWER)
        search(client, "Banani")
        success_ttl = search_cache.seconds_until_expiry("Banani")

        assert 0 < failure_ttl <= database.GEOCODE_FAILURE_TTL.total_seconds()
        assert failure_ttl < success_ttl

    def test_an_expired_failure_lets_the_next_search_try_again(
        self, client, upstream, search_cache
    ):
        """A block lifting has to be noticed without a deploy."""
        upstream.replies(status_code=403, text="blocked")
        assert search(client).status_code == 502

        search_cache.expire("Dhanmondi")
        upstream.replies(status_code=200, json=NOMINATIM_ANSWER)

        assert search(client).status_code == 200
        assert len(upstream.requests) == 2


class TestOneQueryOneRow:
    """Normalisation, so near-identical typing shares an entry."""

    def test_case_and_surrounding_space_collapse(self, client, upstream, search_cache):
        upstream.replies(status_code=200, json=NOMINATIM_ANSWER)

        search(client, "Dhanmondi")
        search(client, "  DHANMONDI  ")
        search(client, "dhanmondi")

        assert len(upstream.requests) == 1
        assert search_cache.count() == 1

    def test_internal_whitespace_collapses(self, client, upstream, search_cache):
        upstream.replies(status_code=200, json=NOMINATIM_ANSWER)

        search(client, "new market")
        search(client, "new    market")

        assert len(upstream.requests) == 1
        assert search_cache.count() == 1

    def test_two_bengali_spellings_of_the_same_word_share_a_row(
        self, client, upstream, search_cache
    ):
        """NFC, and it is not decorative.

        Bengali has more than one valid codepoint sequence for the same visible
        text — য় exists precomposed and as য plus a nukta. Without normalising,
        the same word typed on two keyboards would be two cache keys and two
        requests.
        """
        precomposed = "বরুয়া"
        decomposed = "বরুয়া"
        assert precomposed != decomposed, "premise moved: these are the same bytes"

        upstream.replies(status_code=200, json=NOMINATIM_ANSWER)
        search(client, precomposed)
        search(client, decomposed)

        assert len(upstream.requests) == 1
        assert search_cache.count() == 1

    def test_different_queries_do_not_share_a_row(self, client, upstream, search_cache):
        """The obvious way to make every test above pass wrongly."""
        upstream.replies(status_code=200, json=NOMINATIM_ANSWER)

        search(client, "Dhanmondi")
        search(client, "Gulshan")

        assert len(upstream.requests) == 2
        assert search_cache.count() == 2


class TestExpiry:
    def test_an_expired_answer_is_fetched_again(self, client, upstream, search_cache):
        upstream.replies(status_code=200, json=NOMINATIM_ANSWER)
        search(client)
        assert len(upstream.requests) == 1

        search_cache.expire("Dhanmondi")
        search(client)

        assert len(upstream.requests) == 2

    def test_a_refetch_overwrites_rather_than_adding(
        self, client, upstream, search_cache
    ):
        """The key is the normalised query, so the table is bounded by distinct
        searches rather than by time."""
        upstream.replies(status_code=200, json=NOMINATIM_ANSWER)
        search(client)
        search_cache.expire("Dhanmondi")
        search(client)

        assert search_cache.count() == 1


class TestTheCacheIsAnOptimisationNotADependency:
    """A cache that can take the feature down with it is not a cache.

    Neon drops connections — it has done so repeatedly while this suite runs —
    and Render's free tier sleeps. Search must survive that: the upstream call
    is the source of truth and the cache only saves a trip to it.
    """

    def test_a_failed_cache_read_still_returns_nominatim_results(
        self, client, upstream, monkeypatch
    ):
        """The question this class exists to answer."""
        def unreachable(*args, **kwargs):
            raise psycopg.OperationalError("server closed the connection unexpectedly")

        monkeypatch.setattr(main, "lookup_search_results", unreachable)
        upstream.replies(status_code=200, json=NOMINATIM_ANSWER)

        response = search(client)

        assert response.status_code == 200, (
            "a dropped database connection took out search entirely"
        )
        assert response.json()["results"][0]["name"].startswith("Dhanmondi")
        assert len(upstream.requests) == 1, "never even asked Nominatim"

    def test_a_failed_cache_write_still_returns_results(
        self, client, upstream, monkeypatch
    ):
        """The answer is already in hand; failing to file it must not lose it."""
        def unreachable(*args, **kwargs):
            raise psycopg.OperationalError("server closed the connection unexpectedly")

        monkeypatch.setattr(main, "cache_search_results", unreachable)
        upstream.replies(status_code=200, json=NOMINATIM_ANSWER)

        response = search(client)

        assert response.status_code == 200
        assert response.json()["results"][0]["name"].startswith("Dhanmondi")

    def test_a_failed_failure_write_still_reports_the_upstream_error(
        self, client, upstream, monkeypatch
    ):
        """Two things broken at once must still give the caller the real reason."""
        def unreachable(*args, **kwargs):
            raise psycopg.OperationalError("server closed the connection unexpectedly")

        monkeypatch.setattr(main, "cache_search_failure", unreachable)
        upstream.replies(status_code=403, text="blocked")

        response = search(client)

        # 502 — Nominatim is the thing that failed. Not a 500 from the cache
        # write that was only trying to remember it.
        assert response.status_code == 502
        assert isinstance(response.json()["detail"], str)
