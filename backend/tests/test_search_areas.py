"""Areas are not places to stand.

A search for "Badda" returned the area's label point, which sat in a lake. OSRM
snapped it to a road somewhere else and the fare was priced for a trip nobody
asked for. The fix is to tell the frontend which results are areas, so it can
show the area and let the user tap the real spot instead of dropping a pin.

The rank and box values below are the ones Nominatim returned live for these
queries, so the threshold is tested against what the provider actually sends.
"""

import database
import main
import pytest


def nominatim(name, rank, boundingbox=None, lat="23.78", lon="90.42"):
    """One raw Nominatim result, as /search receives it."""
    place = {
        "display_name": f"{name}, Dhaka, Dhaka Metropolitan, Bangladesh",
        "lat": lat,
        "lon": lon,
        "place_rank": rank,
    }
    if boundingbox is not None:
        place["boundingbox"] = boundingbox
    return place


BADDA_BOX = ["23.7612", "23.7970", "90.4062", "90.4486"]
MALL_BOX = ["23.7501", "23.7513", "90.3920", "90.3934"]


class TestWhatCountsAsAnArea:
    @pytest.mark.parametrize(
        "rank, kind",
        [(18, "borough"), (19, "suburb"), (20, "quarter"), (22, "neighbourhood"), (25, "last area rank")],
    )
    def test_below_street_rank_is_an_area(self, rank, kind):
        place = main._nominatim_place(nominatim("Badda", rank, BADDA_BOX))

        assert place["is_area"] is True, f"rank {rank} ({kind}) should be an area"

    @pytest.mark.parametrize(
        "rank, kind",
        [(26, "major street"), (27, "minor street"), (30, "building or POI")],
    )
    def test_streets_and_places_stay_points(self, rank, kind):
        """A street's coordinate lies on the street, so it still routes true."""
        place = main._nominatim_place(nominatim("Bashundhara City", rank, MALL_BOX))

        assert place["is_area"] is False, f"rank {rank} ({kind}) should be a point"

    def test_the_threshold_is_the_street_rank(self):
        """Pinned, so moving it is a decision rather than an accident."""
        assert main.AREA_RANK_THRESHOLD == 26


class TestTheBox:
    def test_is_reordered_into_leaflet_corners(self):
        """Nominatim sends [south, north, west, east]; Leaflet wants
        [[south, west], [north, east]]."""
        place = main._nominatim_place(nominatim("Badda", 18, BADDA_BOX))

        assert place["bbox"] == [[23.7612, 90.4062], [23.7970, 90.4486]]

    def test_points_carry_their_box_too(self):
        """Harmless, and a provider swap does not have to special-case it."""
        place = main._nominatim_place(nominatim("Bashundhara City", 30, MALL_BOX))

        assert place["bbox"] == [[23.7501, 90.3920], [23.7513, 90.3934]]

    @pytest.mark.parametrize(
        "boundingbox",
        [
            None,                                          # absent
            ["23.76", "23.79", "90.40"],                   # three values
            ["south", "23.79", "90.40", "90.44"],          # not a number
            ["23.79", "23.76", "90.40", "90.44"],          # south above north
        ],
    )
    def test_a_missing_or_malformed_box_leaves_a_point(self, boundingbox):
        """An area with nothing to fit the map to would leave the user with
        neither a pin nor a view. Falling back to a point is what every result
        was before this existed."""
        place = main._nominatim_place(nominatim("Badda", 18, boundingbox))

        assert place["bbox"] is None
        assert place["is_area"] is False

    @pytest.mark.parametrize("rank", [None, "not a rank"])
    def test_a_missing_rank_leaves_a_point(self, rank):
        place = main._nominatim_place(nominatim("Badda", rank, BADDA_BOX))

        assert place["is_area"] is False


class TestThroughTheEndpoint:
    def test_an_area_reaches_the_client_marked(self, client, upstream):
        upstream.replies(
            status_code=200,
            json=[
                nominatim("Badda", 18, BADDA_BOX),
                nominatim("Badda Link Road", 26, ["23.78", "23.79", "90.42", "90.43"]),
            ],
        )

        results = client.get("/search", params={"query": "Badda"}).json()["results"]

        assert [r["is_area"] for r in results] == [True, False]
        assert results[0]["bbox"] == [[23.7612, 90.4062], [23.7970, 90.4486]]


class TestCacheEntriesFromBeforeThisChange:
    """v1 rows have no is_area and no bbox. Read as current, a district would
    come back without its area flag and be pinned — the bug itself."""

    OLD_SHAPE = [
        {
            "name": "Badda, Dhaka, Dhaka Metropolitan",
            "full_name": "Badda, Dhaka, Dhaka Metropolitan, Bangladesh",
            "lat": 23.78,
            "lng": 90.42,
        }
    ]

    def test_the_key_carries_the_version(self):
        key = database.search_cache_key("  BADDA ")

        assert key == f"v{database.SEARCH_CACHE_VERSION}:badda"
        assert key != database.normalise_query("  BADDA ")

    def test_an_old_row_is_not_served(self, client, upstream, search_cache):
        """Planted exactly where the previous deploy wrote it: the bare
        normalised query. The new code must look past it to Nominatim."""
        search_cache.store_raw(database.normalise_query("Badda"), self.OLD_SHAPE)
        upstream.replies(status_code=200, json=[nominatim("Badda", 18, BADDA_BOX)])

        response = client.get("/search", params={"query": "Badda"})

        assert response.status_code == 200
        assert len(upstream.requests) == 1, "served the old-shape row instead of asking"
        [result] = response.json()["results"]
        assert result["is_area"] is True
        assert result["bbox"] is not None

    def test_an_old_row_and_a_new_one_coexist(self, client, upstream, search_cache):
        """What a rolling deploy looks like: the old instance still writing v1
        while the new one writes v2. Neither overwrites the other."""
        search_cache.store_raw(database.normalise_query("Badda"), self.OLD_SHAPE)
        upstream.replies(status_code=200, json=[nominatim("Badda", 18, BADDA_BOX)])

        client.get("/search", params={"query": "Badda"})

        assert search_cache.count() == 2
        assert search_cache.results_for("Badda")[0]["is_area"] is True
