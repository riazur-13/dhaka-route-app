"""Keeping pedal and battery fares apart.

Battery rickshaws are priced below pedal ones deliberately — the motor does the
work the puller's legs would — so a crowd average computed over both drags the
pedal recommendation down toward the battery rate. That is the exact direction
the labour floor in config.py exists to prevent, which is why the split is
worth tests rather than a comment.

The other half of this is that the column cannot be backfilled. Nobody can look
at a stored fare and tell which vehicle it was paid to, so a row written with
the wrong value is wrong permanently. Hence the model rejecting a missing or
invalid vehicle_type outright rather than assuming one.
"""

import database
import main

PEDAL_FARE = {
    "distance_km": 3.0,
    "fare_amount": 95.0,
    "route_type": "rickshaw",
    "vehicle_type": "pedal",
}

BATTERY_FARE = {**PEDAL_FARE, "fare_amount": 60.0, "vehicle_type": "battery"}


def submit(client, payload, ip="203.0.113.9"):
    """One submission. A fresh IP per call keeps the rate limiter out of the way."""
    main.rate_limit_buckets.clear()
    return client.post("/fares", json=payload, headers={"x-forwarded-for": ip})


def recommend(client, vehicle_type="pedal", distance_km=3.0):
    return client.get(
        "/ai-fare-recommendation",
        params={
            "distance_km": distance_km,
            "route_type": "rickshaw",
            "vehicle_type": vehicle_type,
        },
    )


class TestTheModelGuardsTheColumn:
    """Pydantic rejects before Postgres has to. The CHECK is only a backstop."""

    def test_a_submission_without_vehicle_type_is_rejected(self, client):
        payload = {k: v for k, v in PEDAL_FARE.items() if k != "vehicle_type"}

        assert submit(client, payload).status_code == 422

    def test_an_unrecognised_vehicle_type_is_422_not_500(self, client):
        """A bad field is the client's mistake, not the server's.

        Without the Literal this would reach Postgres and trip the CHECK
        constraint, which surfaces as an unhandled exception and a 500 — the
        wrong answer, and one that tells the caller nothing.
        """
        assert submit(client, {**PEDAL_FARE, "vehicle_type": "helicopter"}).status_code == 422

    def test_the_capitalised_spelling_is_rejected_too(self, client):
        """Literal is exact. 'Battery' is not 'battery' and must not be coerced."""
        assert submit(client, {**PEDAL_FARE, "vehicle_type": "Battery"}).status_code == 422

    def test_nothing_is_written_when_the_model_rejects(self, client, fare_db):
        submit(client, {**PEDAL_FARE, "vehicle_type": "Battery"})

        assert fare_db.count() == 0


class TestTheValueIsActuallyStored:
    """A model that accepts a field the INSERT drops would pass every test above."""

    def test_pedal_is_written_to_the_row(self, client, fare_db):
        assert submit(client, PEDAL_FARE).status_code == 200

        rows = fare_db.query("SELECT vehicle_type FROM fare_submissions")
        assert [row[0] for row in rows] == ["pedal"]

    def test_battery_is_written_to_the_row(self, client, fare_db):
        assert submit(client, BATTERY_FARE).status_code == 200

        rows = fare_db.query("SELECT vehicle_type FROM fare_submissions")
        assert [row[0] for row in rows] == ["battery"]

    def test_the_two_are_stored_distinctly(self, client, fare_db):
        """The INSERT reads the submitted value rather than a constant."""
        submit(client, PEDAL_FARE)
        submit(client, BATTERY_FARE)

        rows = fare_db.query(
            "SELECT vehicle_type, fare_amount FROM fare_submissions ORDER BY vehicle_type"
        )
        assert [(row[0], row[1]) for row in rows] == [
            ("battery", 60.0),
            ("pedal", 95.0),
        ]


class TestTheQueryIsScopedToOneVehicle:
    """The behaviour the column was added for."""

    def test_a_pedal_query_does_not_see_battery_rows(self, client, fare_db):
        for _ in range(3):
            submit(client, BATTERY_FARE)

        body = recommend(client, "pedal").json()

        assert body["sample_size"] == 0
        assert body["source"] == "rules"

    def test_a_battery_query_does_not_see_pedal_rows(self, client, fare_db):
        for _ in range(3):
            submit(client, PEDAL_FARE)

        body = recommend(client, "battery").json()

        assert body["sample_size"] == 0

    def test_each_vehicle_counts_only_its_own(self, client, fare_db):
        for _ in range(2):
            submit(client, PEDAL_FARE)
        for _ in range(3):
            submit(client, BATTERY_FARE)

        assert fare_db.count() == 5
        assert recommend(client, "pedal").json()["sample_size"] == 2
        assert recommend(client, "battery").json()["sample_size"] == 3

    def test_rows_predating_the_column_are_excluded_from_both(self, client, fare_db):
        """'unknown' is what the ALTER backfilled existing production rows with.

        A fare whose vehicle nobody recorded is evidence about neither rate, so
        it belongs in neither average. Falling back to the rules-based fare is
        better than quoting a number built from a mixture.
        """
        with database.db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO fare_submissions
                    (distance_km, fare_amount, route_type, vehicle_type)
                VALUES (3.0, 200.0, 'rickshaw', 'unknown')
                """
            )

        assert fare_db.count() == 1
        assert recommend(client, "pedal").json()["sample_size"] == 0
        assert recommend(client, "battery").json()["sample_size"] == 0

    def test_the_pedal_average_is_not_dragged_down_by_battery_fares(
        self, client, fare_db
    ):
        """The whole point, stated as the thing a user would notice.

        Enough pedal submissions to be trusted, plus a pile of much cheaper
        battery ones. If the query mixed them the quoted pedal fare would come
        out below what pedal riders actually reported paying.
        """
        for _ in range(25):
            submit(client, PEDAL_FARE)
        for _ in range(25):
            submit(client, BATTERY_FARE)

        body = recommend(client, "pedal").json()

        assert body["sample_size"] == 25
        assert body["source"] == "crowdsourced"
        # 95 +/-15% — the battery rows at 60 are nowhere in it.
        assert (body["fare_low"], body["fare_high"]) == (81, 109)
