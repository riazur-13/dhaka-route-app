"""The app must accept the fare it just recommended.

It did not. A 7.3 km battery trip was advised at 141-191, and submitting 150
came back "AI Validation Failed: Fare is below realistic lower bound...
indicating likely fake/spam." The user was told a number by one half of the app
and called a liar by the other half for repeating it.

The cause was two rate tables. calculate_logical_bounds had its own,
FARE_RATE_ANCHORS, which was pedal-shaped and not vehicle-aware, and it put the
lower bound at 170 for a trip the rate card priced at 141. Deleting that table
is the fix; this file is what stops it coming back in any form.

These tests are deliberately about the *contract between two endpoints* rather
than either one's internals. Anything either side does — a new widening factor,
a changed rate, different rounding — is free to change as long as the two still
agree, and must fail here the moment they do not.
"""

import pytest

import main

# Distances chosen to cross everything that could disagree: the short-trip flag
# fare, the ordinary middle, the long-trip bend at 8 km, the 15 km "too far for
# a rickshaw" warning, and the reported bug itself at 7.3.
DISTANCES = [0.3, 1.0, 2.5, 4.0, 7.3, 8.0, 8.1, 12.0, 15.0, 22.0, 40.0]
VEHICLES = ["pedal", "battery"]


def recommend(client, distance_km, vehicle_type):
    response = client.get(
        "/ai-fare-recommendation",
        params={
            "distance_km": distance_km,
            "route_type": "rickshaw",
            "vehicle_type": vehicle_type,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def submit(client, distance_km, fare_amount, vehicle_type):
    main.rate_limit_buckets.clear()
    return client.post(
        "/fares",
        json={
            "distance_km": distance_km,
            "fare_amount": fare_amount,
            "route_type": "rickshaw",
            "vehicle_type": vehicle_type,
        },
        headers={"x-forwarded-for": "203.0.113.77"},
    )


@pytest.mark.parametrize("vehicle", VEHICLES)
@pytest.mark.parametrize("distance", DISTANCES)
def test_the_recommended_low_end_is_accepted(client, fare_db, distance, vehicle):
    """The exact number a user reads off the screen and types in."""
    fare = recommend(client, distance, vehicle)

    response = submit(client, distance, fare["fare_low"], vehicle)

    assert response.status_code == 200, (
        f"{distance} km {vehicle}: recommended "
        f"{fare['fare_low']}-{fare['fare_high']} but rejected {fare['fare_low']} "
        f"— {response.json().get('detail')}"
    )


@pytest.mark.parametrize("vehicle", VEHICLES)
@pytest.mark.parametrize("distance", DISTANCES)
def test_the_recommended_high_end_is_accepted(client, fare_db, distance, vehicle):
    fare = recommend(client, distance, vehicle)

    response = submit(client, distance, fare["fare_high"], vehicle)

    assert response.status_code == 200, (
        f"{distance} km {vehicle}: recommended "
        f"{fare['fare_low']}-{fare['fare_high']} but rejected {fare['fare_high']} "
        f"— {response.json().get('detail')}"
    )


@pytest.mark.parametrize("vehicle", VEHICLES)
@pytest.mark.parametrize("distance", DISTANCES)
def test_the_middle_of_the_recommendation_is_accepted(
    client, fare_db, distance, vehicle
):
    fare = recommend(client, distance, vehicle)
    middle = round((fare["fare_low"] + fare["fare_high"]) / 2)

    assert submit(client, distance, middle, vehicle).status_code == 200


def test_the_exact_reported_bug(client, fare_db):
    """7.3 km battery, advised 141-191, submitting 150 was called spam.

    Kept as its own test with its own numbers, because a parametrised sweep
    passing tells you the class of bug is gone but not that this one is.
    """
    fare = recommend(client, 7.3, "battery")

    # Both ends floored to tens for display, so the band a user actually sees.
    assert (fare["fare_low"], fare["fare_high"]) == (140, 190)

    assert submit(client, 7.3, 150, "battery").status_code == 200
    assert submit(client, 7.3, 141, "battery").status_code == 200
    assert submit(client, 7.3, 191, "battery").status_code == 200


def test_a_battery_fare_is_not_judged_against_a_pedal_window(client, fare_db):
    """The mechanism of the bug, stated directly.

    A battery fare sits below the pedal band for the same distance. Before the
    window became vehicle-aware that was enough on its own to be rejected.
    """
    battery = recommend(client, 7.3, "battery")
    pedal = recommend(client, 7.3, "pedal")

    assert battery["fare_low"] < pedal["fare_low"]
    # The battery low end is under the pedal one and must still be accepted.
    assert submit(client, 7.3, battery["fare_low"], "battery").status_code == 200


class TestTheWindowStillCatchesLies:
    """Widening it must not have turned it off."""

    @pytest.mark.parametrize("vehicle", VEHICLES)
    def test_far_too_little_is_rejected(self, client, fare_db, vehicle):
        assert submit(client, 20.0, 50.0, vehicle).status_code == 400

    @pytest.mark.parametrize("vehicle", VEHICLES)
    def test_far_too_much_is_rejected(self, client, fare_db, vehicle):
        assert submit(client, 2.0, 2000.0, vehicle).status_code == 400

    def test_nothing_absurd_is_stored(self, client, fare_db):
        submit(client, 20.0, 50.0, "pedal")
        submit(client, 2.0, 2000.0, "pedal")

        assert fare_db.count() == 0


class TestDisplayRounding:
    """The endpoint's side of the rounding: that it is applied at all.

    What the rule *is* — floor both ends, clamp at the labour floor, never
    collapse — is pure arithmetic and is swept exhaustively in
    test_fare_calculator.py::TestDisplayRounding, which needs no database. What
    is checked here is only that the endpoint actually calls it, on a few
    representative distances rather than every one.
    """

    @pytest.mark.parametrize("vehicle", VEHICLES)
    @pytest.mark.parametrize("distance", [0.3, 7.3, 22.0])
    def test_both_ends_are_multiples_of_ten(self, client, fare_db, distance, vehicle):
        fare = recommend(client, distance, vehicle)

        assert fare["fare_low"] % 10 == 0
        assert fare["fare_high"] % 10 == 0

    def test_the_reported_case_floors_both_ends(self, client, fare_db):
        """5.7 km battery computed 114-154 and was served unrounded.

        110, not 120: the low end floors. That is what separates this rule from
        the low-up one it replaces, and from round-to-nearest.
        """
        fare = recommend(client, 5.7, "battery")

        assert (fare["fare_low"], fare["fare_high"]) == (110, 150)

    def test_the_clamp_fires_through_the_endpoint(self, client, fare_db):
        """0.6 km pedal: exact 31-42, floor 31, flooring would give 30."""
        from fare_calculator import calculate_floor

        fare = recommend(client, 0.6, "pedal")

        assert (fare["fare_low"], fare["fare_high"]) == (40, 50)
        assert fare["fare_low"] >= calculate_floor(0.6, "pedal")

    def test_the_average_is_rounded_for_display_but_stored_exactly(
        self, client, fare_db
    ):
        """Lossy in the panel, exact in the table."""
        for amount in (95.0, 97.0, 99.0):
            assert submit(client, 3.0, amount, "pedal").status_code == 200

        body = client.get(
            "/fares/average",
            params={"distance_km": 3.0, "route_type": "rickshaw", "vehicle_type": "pedal"},
        ).json()

        # Mean of 95, 97, 99 is exactly 97 — displayed as 100.
        assert body["average_fare"] == 100

        stored = fare_db.query("SELECT fare_amount FROM fare_submissions ORDER BY fare_amount")
        assert [row[0] for row in stored] == [95.0, 97.0, 99.0]


class TestThePromptAndTheFieldsAgree:
    """The miss that made the bug visible.

    Groq is handed the numbers and writes them into the Bengali sentence, so an
    unrounded figure in the prompt reaches the user even when the JSON fields
    are correct. One value, two consumers — this is what holds them together.
    """

    # groq_prompt lives in conftest.py — the prose-framing tests need the same
    # capture, and two copies of a fixture is two things to keep in step.

    @pytest.mark.parametrize(
        "distance,vehicle",
        [(0.6, "pedal"), (5.7, "battery"), (22.0, "pedal")],
        ids=["clamped", "the reported case", "long trip"],
    )
    def test_the_prompt_quotes_the_same_numbers_as_the_fields(
        self, client, fare_db, groq_prompt, distance, vehicle
    ):
        fare = recommend(client, distance, vehicle)

        prompt = groq_prompt["prompt"]
        assert f"৳{fare['fare_low']} to ৳{fare['fare_high']}" in prompt, (
            f"prompt and fields disagree at {distance} km {vehicle}: fields say "
            f"{fare['fare_low']}-{fare['fare_high']}, prompt says: {prompt}"
        )

    def test_the_prompt_never_carries_the_unrounded_figures(
        self, client, fare_db, groq_prompt
    ):
        """The exact symptom: 114 and 154 appeared in the Bengali prose."""
        from fare_calculator import calculate_fare

        exact = calculate_fare(5.7, "battery", None, 0)
        assert (exact["low"], exact["high"]) == (114, 154), "premise moved"

        recommend(client, 5.7, "battery")

        prompt = groq_prompt["prompt"]
        assert "114" not in prompt
        assert "154" not in prompt
        assert "৳110 to ৳150" in prompt
