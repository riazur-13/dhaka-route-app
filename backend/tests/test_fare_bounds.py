"""Bounds used to decide whether a submitted fare is plausible.

The bounds are a step in the submission path, so a regression here silently
rejects real fares rather than crashing anything. That makes them worth pinning
down explicitly.

Every test runs for both vehicles now. The window used to be computed from a
rate table of its own, which was pedal-shaped and applied to battery
submissions too — see test_fare_consistency.py for the bug that came of it.
"""

import pytest

import main
from fare_calculator import billable_distance
from main import calculate_logical_bounds as bounds

VEHICLES = ("pedal", "battery")


def distances(start, stop, step):
    value = start
    while value <= stop:
        yield round(value, 2)
        value = round(value + step, 2)


@pytest.mark.parametrize("vehicle", VEHICLES)
def test_no_cliff_at_the_twelve_km_seam(vehicle):
    """The original bug: banded rates jumped at 12 km.

    30-40 Tk/km applied up to 12.0 km and 50-120 Tk/km from 12.01 km, so the
    upper band's floor sat above the lower band's ceiling and a fare accepted
    at 12 km was rejected one tenth of a kilometre later.
    """
    low_12, high_12 = bounds(12.0, vehicle)
    low_121, high_121 = bounds(12.1, vehicle)

    assert low_121 <= high_12
    # A fare comfortably inside the window at 12 km stays inside it at 12.1 km.
    midpoint = (low_12 + high_12) / 2
    assert low_121 <= midpoint <= high_121


@pytest.mark.parametrize("vehicle", VEHICLES)
def test_no_cliff_at_the_five_km_seam(vehicle):
    """The same defect existed at the 5 km band edge."""
    low_5, high_5 = bounds(5.0, vehicle)
    low_51, high_51 = bounds(5.1, vehicle)

    assert low_51 <= high_5
    midpoint = (low_5 + high_5) / 2
    assert low_51 <= midpoint <= high_51


@pytest.mark.parametrize("vehicle", VEHICLES)
def test_no_cliff_at_the_long_trip_bend(vehicle):
    """The rate card has one seam of its own, at LONG_TRIP_THRESHOLD_KM.

    It bends rather than steps, and this is what holds it to that.
    """
    low_8, high_8 = bounds(8.0, vehicle)
    low_81, high_81 = bounds(8.1, vehicle)

    assert low_81 <= high_8
    midpoint = (low_8 + high_8) / 2
    assert low_81 <= midpoint <= high_81


@pytest.mark.parametrize("vehicle", VEHICLES)
def test_bounds_are_continuous_across_the_whole_range(vehicle):
    """No 0.01 km step may move either bound by more than a few taka."""
    previous = bounds(0.01, vehicle)

    for km in distances(0.02, 60.0, 0.01):
        current = bounds(km, vehicle)
        assert abs(current[0] - previous[0]) < 5.0, f"min jumps at {km} km"
        assert abs(current[1] - previous[1]) < 5.0, f"max jumps at {km} km"
        previous = current


@pytest.mark.parametrize("vehicle", VEHICLES)
def test_minimum_never_exceeds_maximum(vehicle):
    for km in distances(0.1, 60.0, 0.1):
        low, high = bounds(km, vehicle)
        assert low < high, f"inverted window at {km} km"


@pytest.mark.parametrize("vehicle", VEHICLES)
def test_short_trips_respect_the_flag_fare_floor(vehicle):
    """A pure per-km rate priced a 0.3 km hop at 9 Tk and rejected reality."""
    for km in (0.1, 0.3, 0.5, 1.0):
        low, high = bounds(km, vehicle)
        assert low >= main.MIN_PLAUSIBLE_FARE
        assert high >= main.MIN_PLAUSIBLE_CEILING

    # 30 Tk for a short hop is what a puller actually charges; it must pass.
    low, high = bounds(0.3, vehicle)
    assert low <= 30.0 <= high


@pytest.mark.parametrize("vehicle", VEHICLES)
def test_the_long_trip_premium_survives_in_the_bounds(vehicle):
    """Replaces test_rates_climb_with_distance, which cannot hold any more.

    That test asserted the *average* per-km rate never falls with distance. It
    passed against FARE_RATE_ANCHORS because those were pure per-km rates that
    climbed by construction. The rate card this now derives from charges a flag
    fare plus a per-km rate, and a flag fare amortises: the average rate falls
    from 20 Tk/km at 1 km to 12 Tk/km at 10 km no matter how the bounds are
    built. Keeping the old assertion would mean keeping a second rate table,
    which is the thing being deleted.

    What the old test was really protecting — longer trips carry a premium — is
    still true, and lives in the *marginal* rate past the bend. This checks
    that, which is the honest form of the same claim.
    """
    def marginal_rate(km):
        low, _ = bounds(km, vehicle)
        return (low - main.MIN_PLAUSIBLE_FARE) / billable_distance(km)

    # Past the point where the short-trip floor stops binding, the per-billable-
    # kilometre rate is flat, and billable distance itself grows faster than
    # real distance beyond the threshold. So a long trip costs more per real
    # kilometre than a short one.
    short = bounds(4.0, vehicle)[0] / 4.0
    long = bounds(30.0, vehicle)[0] / 30.0
    assert long > short, "the long-trip premium has gone"

    # And it is monotone in billable terms, with no seam.
    #
    # The tolerance is for rounding, not for slack. calculate_fare returns whole
    # taka, so dividing an integer by a growing distance makes the observed rate
    # jitter either side of the real one — about 0.002 Tk/km at 17 km, where the
    # underlying rate is exactly flat. A tolerance below the rounding
    # granularity would be testing float noise rather than the rate card.
    previous = marginal_rate(2.0)
    for km in distances(2.0, 60.0, 0.5):
        rate = marginal_rate(km)
        assert rate >= previous - 0.05, f"marginal rate drops at {km} km"
        previous = rate


def test_battery_bounds_sit_below_pedal_bounds():
    """The whole reason the window had to become vehicle-aware."""
    for km in (1.0, 3.0, 7.3, 15.0, 30.0):
        pedal_low, pedal_high = bounds(km, "pedal")
        battery_low, battery_high = bounds(km, "battery")

        assert battery_high < pedal_high, f"battery ceiling not lower at {km} km"
        # The low ends can meet at the short-trip floor, which is a flag fare
        # and the same for both, so this is <= rather than <.
        assert battery_low <= pedal_low, f"battery floor above pedal at {km} km"


def test_the_window_is_wider_than_the_recommendation():
    """It answers a different question and has to have room to.

    A window as tight as the recommended band calls every real-world variation
    a lie — which is precisely what it was doing.
    """
    from fare_calculator import calculate_fare

    for km in (1.0, 3.0, 7.3, 15.0):
        for vehicle in VEHICLES:
            fare = calculate_fare(km, vehicle, None, 0)
            low, high = bounds(km, vehicle)

            assert low < fare["low"], f"window not wider below at {km} km {vehicle}"
            assert high > fare["high"], f"window not wider above at {km} km {vehicle}"


def test_an_unknown_vehicle_type_is_rejected():
    """Deliberately passing what the type system forbids.

    vehicle_type is Literal["pedal", "battery"], so a checker rejects this call
    — which is the point. The annotation stops a mistake reaching here from
    typed code; this test covers the paths that are not typed, like a value
    arriving off the wire. Both guards are wanted, so the ignore is narrow and
    deliberate rather than a way of quieting the checker.
    """
    with pytest.raises(ValueError, match="vehicle_type"):
        bounds(3.0, "helicopter")  # type: ignore[arg-type]
