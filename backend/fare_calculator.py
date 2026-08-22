"""What a rickshaw trip should cost, decided in Python.

This used to be prose inside a prompt: the model was told roughly what Dhaka
rates look like and asked to invent a number. That made the fare
non-deterministic (the same trip priced differently on two clicks), untestable
(there is no assertion you can write against a language model's arithmetic),
and unavailable whenever Groq was down or slow.

Now Python decides the number and Groq only phrases it. The model can still
fail; the fare no longer fails with it.

Everything here is a pure function. No database, no network, no clock, no
randomness — the same arguments always give the same answer, which is what
makes the tests worth having.

The one rule that outranks the others: the floor is applied last, after
crowdsourced data has been taken into account, and crowdsourced data can never
push a recommendation below it. See the policy comment in config.py.
"""

import math
from typing import Literal

from config import (
    CROWDSOURCE_FULL_TRUST,
    CROWDSOURCE_MIN_TRUST,
    FARE_ABSOLUTE_MIN_BDT,
    FARE_BASE_BDT,
    FARE_FLOOR_PER_KM_BATTERY,
    FARE_FLOOR_PER_KM_PEDAL,
    FARE_PER_KM_BATTERY,
    FARE_PER_KM_PEDAL,
    FARE_RANGE_SPREAD,
    LONG_TRIP_MULTIPLIER,
    LONG_TRIP_THRESHOLD_KM,
)

VehicleType = Literal["pedal", "battery"]

FAIR_RATE_PER_KM: dict[str, float] = {
    "pedal": FARE_PER_KM_PEDAL,
    "battery": FARE_PER_KM_BATTERY,
}

# Battery rickshaws sit lower because the motor is doing the work the puller's
# legs would otherwise do. The gap between the two floors is the labour.
FLOOR_RATE_PER_KM: dict[str, float] = {
    "pedal": FARE_FLOOR_PER_KM_PEDAL,
    "battery": FARE_FLOOR_PER_KM_BATTERY,
}


def _rate(table: dict[str, float], vehicle_type: str) -> float:
    try:
        return table[vehicle_type]
    except KeyError:
        raise ValueError(
            f"unknown vehicle_type {vehicle_type!r}; expected 'pedal' or 'battery'"
        ) from None


def billable_distance(distance_km: float) -> float:
    """Distance after the long-trip bend, in kilometres.

    Only the distance *beyond* the threshold is multiplied, not the whole trip.
    That matters: multiplying the whole trip would make the fare jump the moment
    a route crossed 8 km, so a 7.9 km ride and an 8.1 km ride would be priced
    very differently for no reason a passenger could see. Charging only the
    excess keeps the curve continuous — it bends, it does not step.

    This project has been bitten by exactly that before: the submission bounds
    in main.py used flat bands until a fare accepted at 12.0 km was rejected at
    12.1 km.
    """
    if distance_km <= LONG_TRIP_THRESHOLD_KM:
        return distance_km

    excess = distance_km - LONG_TRIP_THRESHOLD_KM
    return LONG_TRIP_THRESHOLD_KM + excess * LONG_TRIP_MULTIPLIER


def _spread(midpoint: float) -> tuple[float, float]:
    """Widen a single number into the band we actually quote."""
    return midpoint * (1 - FARE_RANGE_SPREAD), midpoint * (1 + FARE_RANGE_SPREAD)


def _rules_midpoint(distance_km: float, vehicle_type: str) -> float:
    """The unrounded centre of the rules-based band.

    Kept separate from calculate_rules_fare because blending needs the midpoint
    itself. Rounding then happens once, at the edge, so a blend of two rounded
    numbers cannot drift away from a round of the blended number.
    """
    rate = _rate(FAIR_RATE_PER_KM, vehicle_type)
    return FARE_BASE_BDT + rate * billable_distance(distance_km)


def calculate_rules_fare(
    distance_km: float, vehicle_type: VehicleType
) -> tuple[int, int]:
    """The fare this app considers fair, ignoring what anyone has submitted."""
    low, high = _spread(_rules_midpoint(distance_km, vehicle_type))
    return round(low), round(high)


def calculate_floor(distance_km: float, vehicle_type: VehicleType) -> int:
    """The lowest fare this app will ever recommend for this trip.

    Rounded *up*, not to nearest. A floor that rounds down is not a floor — it
    is a floor minus fifty poisha, every single time.
    """
    rate = _rate(FLOOR_RATE_PER_KM, vehicle_type)
    raw = FARE_BASE_BDT + rate * billable_distance(distance_km)
    return max(math.ceil(raw), FARE_ABSOLUTE_MIN_BDT)


def _crowd_weight(crowd_count: int) -> float:
    """How much of the final midpoint the crowd gets, from 0.0 to 1.0.

    A straight line between the two trust thresholds. The alternative was a
    step at one single sample count, which would mean the eleventh submission
    changed every quoted fare in that distance band overnight.
    """
    span = CROWDSOURCE_FULL_TRUST - CROWDSOURCE_MIN_TRUST
    return (crowd_count - CROWDSOURCE_MIN_TRUST) / span


def calculate_fare(
    distance_km: float,
    vehicle_type: VehicleType,
    crowd_median: float | None,
    crowd_count: int,
) -> dict:
    """Decide the fare band to recommend, and say where the number came from.

    Returns low, high, source, floor_applied and sample_size. `source` exists so
    the caller can be honest with the user about whether they are being told a
    formula's opinion or their neighbours' experience.
    """
    crowd_count = crowd_count or 0
    midpoint = _rules_midpoint(distance_km, vehicle_type)

    # A NULL average alongside a non-zero count should not be possible, but SQL
    # aggregates are exactly where that sort of impossible pair comes from, and
    # treating None as 0.0 would quietly drag every fare toward zero.
    if crowd_median is None or crowd_count < CROWDSOURCE_MIN_TRUST:
        source = "rules"
    elif crowd_count >= CROWDSOURCE_FULL_TRUST:
        midpoint = crowd_median
        source = "crowdsourced"
    else:
        weight = _crowd_weight(crowd_count)
        midpoint = midpoint * (1 - weight) + crowd_median * weight
        source = "blended"

    low, high = _spread(midpoint)
    low_bdt, high_bdt = round(low), round(high)

    # The floor goes on last, on purpose, and applies to every branch above.
    # Submissions arriving below it are evidence that haggling works, not
    # evidence that the fare is fair, so the crowd can move a number up through
    # the floor and never down through it.
    floor = calculate_floor(distance_km, vehicle_type)
    floor_applied = low_bdt < floor

    if floor_applied:
        low_bdt = floor
        # Lifting only the low end inverts the band on short trips: a 0.1 km
        # pedal ride computes 19-26, and clamping the low end alone would quote
        # "30 to 26". So the band is rebuilt around the floor at the same
        # relative width, giving 30-41. Flattening it to 30-30 was the
        # alternative, and a zero-width band tells a passenger to refuse any
        # counter-offer at all — which works against the puller the floor is
        # there to protect.
        high_bdt = round(floor * (1 + FARE_RANGE_SPREAD) / (1 - FARE_RANGE_SPREAD))

    return {
        "low": low_bdt,
        # Belt and braces: no combination of these constants should be able to
        # quote a band that runs backwards, and this is cheaper than finding out
        # that one of them can.
        "high": max(high_bdt, low_bdt),
        "source": source,
        "floor_applied": floor_applied,
        "sample_size": crowd_count,
    }
