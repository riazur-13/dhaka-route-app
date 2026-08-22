"""The fare arithmetic, pinned down.

These tests are the reason the calculation was moved out of the prompt at all.
You cannot assert anything about a number a language model invented; every
assertion below would have been impossible to write a commit ago.

No database and no network here — the module under test is pure, so this file
runs even with TEST_DATABASE_URL unset.

Expected values are written as literals rather than recomputed from config, so
that changing a constant fails a test instead of quietly moving the goalposts
along with it. Where a test is about a *relationship* (battery below pedal, the
floor beating the crowd) it reads the constants, because the relationship is
the thing being protected, not the number.
"""

import config
import pytest
from fare_calculator import calculate_fare, calculate_floor, calculate_rules_fare


class TestKnownDistances:
    """base + rate x distance, spread +/-15%, rounded."""

    def test_three_km_pedal(self):
        # 20 + 25*3 = 95; 95 * 0.85 = 80.75, 95 * 1.15 = 109.25
        assert calculate_rules_fare(3.0, "pedal") == (81, 109)

    def test_three_km_battery(self):
        # 20 + 20*3 = 80; 80 * 0.85 = 68, 80 * 1.15 = 92
        assert calculate_rules_fare(3.0, "battery") == (68, 92)

    def test_the_base_fare_is_charged_at_any_distance(self):
        """A flag fare is a flag fare — it does not scale down to nothing."""
        low, high = calculate_rules_fare(0.0, "pedal")
        midpoint = (low + high) / 2
        assert midpoint == pytest.approx(config.FARE_BASE_BDT, abs=1)

    def test_an_unknown_vehicle_type_is_rejected_loudly(self):
        """Not silently priced as a pedal rickshaw."""
        with pytest.raises(ValueError, match="vehicle_type"):
            calculate_rules_fare(3.0, "helicopter")


class TestLongTripBend:
    """The multiplier applies to the excess distance only."""

    def test_below_the_threshold_there_is_no_bend(self):
        # 20 + 25*5 = 145, untouched by the multiplier
        assert calculate_rules_fare(5.0, "pedal") == (123, 167)

    def test_at_the_threshold_there_is_still_no_bend(self):
        # 20 + 25*8 = 220 exactly
        assert calculate_rules_fare(8.0, "pedal") == (187, 253)

    def test_above_the_threshold_only_the_excess_is_multiplied(self):
        # 20 + 25*8 + 25*1.3*2 = 285, not 20 + 25*1.3*10 = 345
        assert calculate_rules_fare(10.0, "pedal") == (242, 328)

    def test_the_bend_has_no_cliff_at_the_threshold(self):
        """The bug this project already shipped once, in the submission bounds.

        Flat bands there made a fare accepted at 12.0 km rejected at 12.1 km.
        Charging only the excess keeps the curve continuous, so a tenth of a
        kilometre can never be worth more than a couple of taka.
        """
        below_low, below_high = calculate_rules_fare(7.99, "pedal")
        above_low, above_high = calculate_rules_fare(8.01, "pedal")

        assert above_low - below_low < 2
        assert above_high - below_high < 2
        # And it bends upward, not downward.
        assert above_low >= below_low


class TestFloor:
    """The living wage line. Nothing may price below it."""

    def test_battery_floors_below_pedal(self):
        """The gap between the two floors is the puller's legs."""
        for distance in (1.0, 5.0, 10.0, 20.0):
            assert calculate_floor(distance, "battery") < calculate_floor(
                distance, "pedal"
            )

    def test_the_floor_sits_below_the_fair_rate(self):
        """A floor above the fair rate would mean the fair rate is unfair.

        True wherever the per-km floor rate is what is driving the number. It
        is deliberately *not* true on very short trips, where
        FARE_ABSOLUTE_MIN_BDT takes over and lifts the floor above a rate-based
        fare — a 0.5 km ride computes 24-32 but is never worth less than 30 to
        the puller. That case is the clamp's job, and is tested below.
        """
        for distance in (3.0, 8.0, 15.0):
            low, _ = calculate_rules_fare(distance, "pedal")
            assert calculate_floor(distance, "pedal") <= low

    def test_the_absolute_minimum_deliberately_outranks_the_rate_on_short_hops(self):
        """The documented exception to the test above."""
        assert calculate_floor(0.5, "pedal") == config.FARE_ABSOLUTE_MIN_BDT
        assert calculate_floor(0.5, "pedal") > calculate_rules_fare(0.5, "pedal")[0]

    def test_the_floor_bends_on_long_trips_too(self):
        # 20 + 18*8 + 18*1.3*2 = 210.8, rounded up
        assert calculate_floor(10.0, "pedal") == 211

    def test_the_floor_rounds_up_never_down(self):
        """A floor rounded to nearest is a floor breached half the time."""
        # 20 + 18*0.35 = 26.3 -> under the absolute minimum anyway,
        # so use a distance where the raw floor lands mid-taka: 20 + 18*3.75 = 87.5
        assert calculate_floor(3.75, "pedal") == 88

    def test_a_short_trip_never_goes_below_the_absolute_minimum(self):
        assert calculate_floor(0.1, "pedal") == config.FARE_ABSOLUTE_MIN_BDT
        assert calculate_floor(0.1, "battery") == config.FARE_ABSOLUTE_MIN_BDT


class TestCrowdsourceTrust:
    """How much the crowd is believed, and when."""

    def test_no_submissions_means_rules_only(self):
        result = calculate_fare(3.0, "pedal", crowd_median=None, crowd_count=0)

        assert result["source"] == "rules"
        assert (result["low"], result["high"]) == calculate_rules_fare(3.0, "pedal")
        assert result["sample_size"] == 0

    def test_too_few_submissions_are_ignored_entirely(self):
        """Four wildly high fares must not move the recommendation at all."""
        result = calculate_fare(3.0, "pedal", crowd_median=500.0, crowd_count=4)

        assert result["source"] == "rules"
        assert (result["low"], result["high"]) == calculate_rules_fare(3.0, "pedal")

    def test_many_submissions_dominate(self):
        result = calculate_fare(3.0, "pedal", crowd_median=120.0, crowd_count=50)

        assert result["source"] == "crowdsourced"
        # 120 * 0.85 = 102, 120 * 1.15 = 138 — the formula no longer shows.
        assert (result["low"], result["high"]) == (102, 138)

    def test_a_middling_sample_is_blended(self):
        result = calculate_fare(3.0, "pedal", crowd_median=120.0, crowd_count=12)

        assert result["source"] == "blended"
        # weight = (12-5)/(20-5) = 7/15; 95*(8/15) + 120*(7/15) = 106.67
        assert (result["low"], result["high"]) == (91, 123)

    def test_the_blend_moves_monotonically_with_sample_size(self):
        """More agreement with the crowd, the closer the answer sits to it."""
        lows = [
            calculate_fare(3.0, "pedal", crowd_median=200.0, crowd_count=n)["low"]
            for n in range(config.CROWDSOURCE_MIN_TRUST, config.CROWDSOURCE_FULL_TRUST + 1)
        ]
        assert lows == sorted(lows)

    def test_a_null_median_falls_back_to_rules_whatever_the_count_says(self):
        """AVG() over no rows is NULL; treating that as 0 would zero the fare."""
        result = calculate_fare(3.0, "pedal", crowd_median=None, crowd_count=50)

        assert result["source"] == "rules"
        assert (result["low"], result["high"]) == calculate_rules_fare(3.0, "pedal")


class TestFloorBeatsTheCrowd:
    """The clause that makes this a policy and not just a formula."""

    def test_a_low_crowd_median_is_clamped_upward(self):
        """Successful haggling is not evidence of a fair price."""
        result = calculate_fare(3.0, "pedal", crowd_median=40.0, crowd_count=50)

        assert result["floor_applied"] is True
        assert result["low"] == calculate_floor(3.0, "pedal")
        # Still labelled crowdsourced: the crowd was heard, then overruled.
        assert result["source"] == "crowdsourced"

    def test_a_blended_result_is_clamped_too(self):
        """Every branch passes through the floor, not just the crowdsourced one."""
        result = calculate_fare(3.0, "pedal", crowd_median=30.0, crowd_count=10)

        assert result["source"] == "blended"
        assert result["floor_applied"] is True
        assert result["low"] >= calculate_floor(3.0, "pedal")

    def test_a_healthy_crowd_median_is_left_alone(self):
        result = calculate_fare(3.0, "pedal", crowd_median=120.0, crowd_count=50)

        assert result["floor_applied"] is False

    def test_the_crowd_may_still_push_the_fare_up(self):
        """The floor is a floor, not a fixed price — high submissions still count."""
        result = calculate_fare(3.0, "pedal", crowd_median=200.0, crowd_count=50)

        assert result["floor_applied"] is False
        assert result["low"] > calculate_rules_fare(3.0, "pedal")[0]


class TestVeryShortTrips:
    """Where the absolute minimum bites and the band would otherwise invert."""

    def test_a_tenth_of_a_kilometre_returns_the_absolute_minimum(self):
        result = calculate_fare(0.1, "pedal", crowd_median=None, crowd_count=0)

        assert result["low"] == config.FARE_ABSOLUTE_MIN_BDT
        assert result["floor_applied"] is True

    def test_the_band_is_rebuilt_around_the_floor_rather_than_inverting(self):
        """Clamping only the low end would quote "30 to 26" here.

        The raw band for 0.1 km is 19-26. Lifting the low end to the 30 taka
        minimum without touching the high end leaves a range that runs
        backwards, which is worse than wrong — it renders.
        """
        result = calculate_fare(0.1, "pedal", crowd_median=None, crowd_count=0)

        assert result["high"] > result["low"]
        assert (result["low"], result["high"]) == (30, 41)

    def test_no_distance_ever_produces_a_backwards_band(self):
        distances = [d / 10 for d in range(0, 300)]
        for distance in distances:
            for vehicle in ("pedal", "battery"):
                result = calculate_fare(distance, vehicle, None, 0)
                assert result["low"] <= result["high"], (distance, vehicle)
                assert result["low"] >= config.FARE_ABSOLUTE_MIN_BDT

    def test_no_crowd_median_can_produce_a_backwards_band(self):
        for median in (1.0, 25.0, 100.0, 5000.0):
            for count in (0, 5, 12, 20, 500):
                result = calculate_fare(2.0, "pedal", median, count)
                assert result["low"] <= result["high"], (median, count)
