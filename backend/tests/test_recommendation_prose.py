"""What Groq actually writes — the only layer that tests compliance.

    pytest -m live_groq

**These send real Groq completions and cost money.** They are skipped unless
GROQ_API_KEY holds a real key, so they never run in CI, which has no Groq
secret, and never run in the default suite, which bills nobody.

Run them by hand after any change to the recommendation prompt. Everything else
in this suite asserts what the model was *asked*; this is the only thing that
checks what it did with the asking, and nothing gates it. That gap is deliberate
and stated rather than hidden — a live, paid, temperature-0.3 test cannot gate a
branch without becoming the kind of flake people learn to ignore.

The bug being guarded: the Bengali said the fare had been নির্ধারিত
(determined), then advised negotiating in the next sentence. The app read a rate
card. It did not consult an authority, and nothing is settled.
"""

import re

import pytest

import main
from tests.conftest import PLACEHOLDER_GROQ_KEY

# The clear cases. Each asserts the number is settled, which is the
# overstatement. Authority words (সরকারি, অফিসিয়াল) and the ambiguous নির্দিষ্ট
# are deliberately not here: নির্দিষ্ট has legitimate neutral uses — "a specific
# distance" — and would fail on innocent phrasing.
FORBIDDEN = {
    "নির্ধারিত": "determined / fixed",
    "নির্ধারণ": "determination",
    "ধার্য": "levied / imposed",
    "চূড়ান্ত": "final",
}

MAX_SENTENCES = 3

# Bengali ends a sentence with the dari, not a full stop. Latin terminators are
# included because the model sometimes mixes them in around numerals.
SENTENCE_END = re.compile(r"[।.!?]+")

CASES = [
    (0.6, "pedal"),      # the floor clamp fires — different tone branch
    (3.0, "pedal"),
    (5.7, "battery"),    # the reported case
    (15.0, "battery"),   # long enough to trigger the distance warning
]


pytestmark = pytest.mark.live_groq


@pytest.fixture(autouse=True)
def require_a_real_key():
    """Skip unless someone has deliberately supplied a real key."""
    from config import GROQ_API_KEY

    if not GROQ_API_KEY or GROQ_API_KEY == PLACEHOLDER_GROQ_KEY:
        pytest.skip(
            "needs a real GROQ_API_KEY — these send billed completions. "
            "Put one in backend/.env and run: pytest -m live_groq"
        )


def generate(client, distance_km, vehicle_type):
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


def count_sentences(text):
    return len([part for part in SENTENCE_END.split(text) if part.strip()])


@pytest.mark.parametrize("distance,vehicle", CASES)
def test_the_prose_never_calls_the_fare_settled(client, fare_db, distance, vehicle):
    body = generate(client, distance, vehicle)
    prose = body["recommendation"]

    print(f"\n{distance} km {vehicle} -> {body['fare_low']}-{body['fare_high']}\n{prose}")

    assert body["recommendation_available"] is True, "Groq failed; nothing to judge"

    for term, meaning in FORBIDDEN.items():
        assert term not in prose, (
            f"{distance} km {vehicle}: prose used {term} ({meaning}), which "
            f"presents the estimate as settled.\n{prose}"
        )


@pytest.mark.parametrize("distance,vehicle", CASES)
def test_the_prose_stays_within_the_length_limit(client, fare_db, distance, vehicle):
    body = generate(client, distance, vehicle)
    prose = body["recommendation"]

    sentences = count_sentences(prose)

    assert sentences <= MAX_SENTENCES, (
        f"{distance} km {vehicle}: {sentences} sentences, limit is "
        f"{MAX_SENTENCES}.\n{prose}"
    )


@pytest.mark.parametrize("distance,vehicle", CASES)
def test_the_token_budget_did_not_starve_the_answer(
    client, fare_db, distance, vehicle
):
    """The check on lowering max_tokens.

    Reasoning tokens are billed against the budget and emitted before any
    content, so cutting it too far returns HTTP 200 with content=None. The
    endpoint handles that gracefully, which is exactly why it would go unnoticed
    without this.
    """
    body = generate(client, distance, vehicle)

    assert body["recommendation_available"] is True, (
        f"{distance} km {vehicle}: empty completion — max_tokens is likely too "
        "low for the reasoning budget."
    )
    assert body["recommendation"].strip()


@pytest.mark.parametrize("distance,vehicle", CASES)
def test_the_prose_quotes_the_fare_it_was_given(client, fare_db, distance, vehicle):
    """The model must not invent a number, in any script.

    Bengali digits are a real possibility here, so both forms are accepted —
    the point is that the figures are ours, not that they are Latin.
    """
    body = generate(client, distance, vehicle)
    prose = body["recommendation"]

    def in_either_script(number):
        latin = str(number)
        bengali = latin.translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))
        return latin in prose or bengali in prose

    assert in_either_script(body["fare_low"]), f"low end missing\n{prose}"
    assert in_either_script(body["fare_high"]), f"high end missing\n{prose}"
