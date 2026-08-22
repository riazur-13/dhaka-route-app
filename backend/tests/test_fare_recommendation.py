"""The /ai-fare-recommendation endpoint, after the fare moved out of the prompt.

The calculator itself is covered by test_fare_calculator.py. What is tested here
is the endpoint's side of the bargain: that the numbers are computed in Python,
that they survive every way Groq can fail, and that a completion carrying no
text is treated as a failure rather than served as an answer.
"""

import types

import main
import pytest


def _completion(content, finish_reason="stop"):
    """One Groq response. `content` may be None — that is the point of it."""
    message = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(message=message, finish_reason=finish_reason)
    return types.SimpleNamespace(choices=[choice])


@pytest.fixture
def groq_says(monkeypatch):
    """Set what the model returns, or raises, for the recommendation call."""

    def _set(content=None, finish_reason="stop", raises=None):
        def create(**kwargs):
            if raises is not None:
                raise raises
            return _completion(content, finish_reason)

        monkeypatch.setattr(
            main,
            "groq_client",
            types.SimpleNamespace(
                chat=types.SimpleNamespace(
                    completions=types.SimpleNamespace(create=create)
                )
            ),
        )

    return _set


def recommend(client, **params):
    params.setdefault("distance_km", 3.0)
    params.setdefault("route_type", "rickshaw")
    return client.get("/ai-fare-recommendation", params=params)


BENGALI = "এই দূরত্বের জন্য ভাড়া যুক্তিসঙ্গত। দরদাম করে নিন। শুভ যাত্রা।"


def test_the_fare_comes_from_python_not_from_the_model(client, groq_says):
    """The model is handed the number; it never gets to pick one."""
    groq_says(content=BENGALI)

    body = recommend(client).json()

    # 20 + 25*3 = 95, spread +/-15%. Asserted as literals because the whole
    # point of the change is that this is now predictable.
    assert body["fare_low"] == 81
    assert body["fare_high"] == 109
    assert body["source"] == "rules"
    assert body["sample_size"] == 0
    assert body["floor_applied"] is False
    assert body["recommendation_available"] is True
    assert body["recommendation"] == BENGALI


def test_the_same_trip_priced_twice_gives_the_same_answer(client, groq_says):
    """It could not before: the number was whatever the model felt like."""
    groq_says(content=BENGALI)

    first = recommend(client).json()
    second = recommend(client).json()

    assert (first["fare_low"], first["fare_high"]) == (
        second["fare_low"],
        second["fare_high"],
    )


class TestTheNumbersSurviveGroq:
    """A missing Bengali sentence is a missing wrapper, not a missing fare."""

    def test_an_outage_still_returns_the_fare(self, client, groq_says):
        groq_says(raises=RuntimeError("Invalid API Key sk-secret-abc123"))

        response = recommend(client)
        body = response.json()

        assert response.status_code == 200
        assert (body["fare_low"], body["fare_high"]) == (81, 109)
        assert body["recommendation_available"] is False
        assert body["recommendation"]

    def test_the_exception_text_is_never_returned_to_the_client(
        self, client, groq_says
    ):
        """It can name credentials; it reaches a browser."""
        groq_says(raises=RuntimeError("Invalid API Key sk-secret-abc123"))

        assert "sk-secret" not in recommend(client).text

    def test_a_null_completion_is_a_failure_not_an_answer(self, client, groq_says):
        """The bug this rewrite closes.

        gpt-oss-20b is a reasoning model: reasoning tokens are billed against
        max_tokens and emitted before any content, so hitting the ceiling
        returns HTTP 200 with content=None. The endpoint used to hand that
        straight back as {"recommendation": null} with a 200 and nothing in the
        log — the same failure that surfaced as json_validate_failed on the
        validation call, but silent.
        """
        groq_says(content=None, finish_reason="length")

        body = recommend(client).json()

        assert body["recommendation_available"] is False
        assert body["recommendation"] is not None
        assert (body["fare_low"], body["fare_high"]) == (81, 109)

    def test_a_whitespace_only_completion_is_also_a_failure(self, client, groq_says):
        groq_says(content="   \n  ")

        assert recommend(client).json()["recommendation_available"] is False

    def test_an_empty_completion_is_logged(self, client, groq_says, caplog):
        """Silence was half the problem — nothing in the log said it happened."""
        groq_says(content=None, finish_reason="length")

        with caplog.at_level("WARNING"):
            recommend(client)

        # getMessage(), not .message: caplog has already interpolated the args
        # into .message, and applying them a second time raises TypeError.
        assert any("empty recommendation" in r.getMessage() for r in caplog.records)
        assert any("finish_reason=length" in r.getMessage() for r in caplog.records)


class TestVehicleType:
    def test_it_defaults_to_pedal(self, client, groq_says):
        """Nothing upstream sets it yet, so the default has to be the safe one.

        Pedal carries the higher floor of the two, so defaulting here can never
        under-price a puller's labour.
        """
        groq_says(content=BENGALI)

        default = recommend(client).json()
        pedal = recommend(client, vehicle_type="pedal").json()

        assert default["fare_low"] == pedal["fare_low"]

    def test_battery_is_priced_below_pedal(self, client, groq_says):
        groq_says(content=BENGALI)

        pedal = recommend(client, vehicle_type="pedal").json()
        battery = recommend(client, vehicle_type="battery").json()

        assert battery["fare_low"] < pedal["fare_low"]

    def test_an_unknown_vehicle_type_is_a_400_not_a_500(self, client, groq_says):
        """The calculator raises ValueError; unhandled that is a 500."""
        groq_says(content=BENGALI)

        assert recommend(client, vehicle_type="helicopter").status_code == 400


class TestCrowdsourcedData:
    """The endpoint's own wiring: what it reads out of the table.

    How the crowd's number is weighted is the calculator's business and is
    tested exhaustively in test_fare_calculator.py. All that is checked here is
    that the endpoint reads the table at all and passes on what it finds.
    """

    def test_an_empty_table_gives_rules_and_a_zero_sample(self, client, groq_says):
        groq_says(content=BENGALI)

        body = recommend(client).json()

        assert body["source"] == "rules"
        assert body["sample_size"] == 0

    def test_the_sample_size_reflects_what_is_in_the_table(
        self, client, groq_says, fare_db
    ):
        groq_says(content=BENGALI)

        body = recommend(client).json()

        assert body["sample_size"] == fare_db.count()
