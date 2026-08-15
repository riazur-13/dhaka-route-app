"""Bounds used to decide whether a submitted fare is plausible.

The bounds are a step in the submission path, so a regression here silently
rejects real fares rather than crashing anything. That makes them worth
pinning down explicitly.
"""

import main
from main import calculate_logical_bounds as bounds


def distances(start, stop, step):
    value = start
    while value <= stop:
        yield round(value, 2)
        value = round(value + step, 2)


def test_no_cliff_at_the_twelve_km_seam():
    """The original bug: banded rates jumped at 12 km.

    30-40 Tk/km applied up to 12.0 km and 50-120 Tk/km from 12.01 km, so the
    upper band's floor sat above the lower band's ceiling and a fare accepted
    at 12 km was rejected one tenth of a kilometre later.
    """
    low_12, high_12 = bounds(12.0)
    low_121, high_121 = bounds(12.1)

    assert low_121 <= high_12
    # A fare comfortably inside the window at 12 km stays inside it at 12.1 km.
    midpoint = (low_12 + high_12) / 2
    assert low_121 <= midpoint <= high_121


def test_no_cliff_at_the_five_km_seam():
    """The same defect existed at the 5 km band edge."""
    low_5, high_5 = bounds(5.0)
    low_51, high_51 = bounds(5.1)

    assert low_51 <= high_5
    midpoint = (low_5 + high_5) / 2
    assert low_51 <= midpoint <= high_51


def test_bounds_are_continuous_across_the_whole_range():
    """No 0.01 km step may move either bound by more than a few taka."""
    previous = bounds(0.01)

    for km in distances(0.02, 60.0, 0.01):
        current = bounds(km)
        assert abs(current[0] - previous[0]) < 5.0, f"min jumps at {km} km"
        assert abs(current[1] - previous[1]) < 5.0, f"max jumps at {km} km"
        previous = current


def test_minimum_never_exceeds_maximum():
    for km in distances(0.1, 60.0, 0.1):
        low, high = bounds(km)
        assert low < high, f"inverted window at {km} km"


def test_short_trips_respect_the_flag_fare_floor():
    """A pure per-km rate priced a 0.3 km hop at 9 Tk and rejected reality."""
    for km in (0.1, 0.3, 0.5, 1.0):
        low, high = bounds(km)
        assert low >= main.MIN_PLAUSIBLE_FARE
        assert high >= main.MIN_PLAUSIBLE_CEILING

    # 30 Tk for a short hop is what a puller actually charges; it must pass.
    low, high = bounds(0.3)
    assert low <= 30.0 <= high


def test_rates_climb_with_distance():
    """Longer trips carry a fatigue premium, so per-km rates never decrease."""
    previous_rate = 0.0
    for km in distances(1.0, 60.0, 0.5):
        low, _ = bounds(km)
        rate = low / km
        assert rate >= previous_rate - 1e-9, f"per-km rate drops at {km} km"
        previous_rate = rate
