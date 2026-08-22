"""Every value the backend reads from the environment, in one place.

Two things this file exists to prevent.

The first is whitespace. A DATABASE_URL pasted into the Render dashboard with a
trailing newline took a deploy down: the newline travelled into the connection
string and the pool could not connect, with an error that pointed at the
database rather than at the paste. Dashboards, .env files and shell exports all
make that easy to do and none of them make it visible. So every variable is read
through get_env(), which strips it — the fix lives at the one point where values
enter the process rather than at each of the places they are used.

The second is a model id spelled out at more than one call site.
llama-3.3-70b-versatile was named twice, and when Groq decommissioned it both
call sites started failing at once. Because both of them catch exceptions and
fall back quietly, the endpoints kept returning 200 with the AI silently absent.
One value, overridable from the environment, means the next decommissioning is a
dashboard edit and not a deploy.
"""

import os
from typing import overload

from dotenv import load_dotenv

# Loaded here, not in main.py, so that anything importing config gets the .env
# values whether or not main has been imported first.
load_dotenv()

# Groq's free tier as of the llama-3.3-70b-versatile decommissioning. Override
# with GROQ_MODEL rather than editing this, so a model going away does not
# need a code change.
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"

# Nominatim's usage policy asks for a User-Agent that both names the application
# and gives them a way to reach whoever runs it; a bare product token is the
# shape their blocklists look for. The URL is the contact point. Overridable so
# that a fork, or a second deployment, can identify itself as itself rather than
# inheriting the blame — or the block — for this one.
DEFAULT_USER_AGENT = "DhakaRouteFinder/1.0 (github.com/riazur-13/dhaka-route-app)"


# The overloads are what let callers with a default treat the result as a plain
# str: without them every use site inherits an Optional it can never actually
# receive, and has to assert it away.
@overload
def get_env(name: str, default: str) -> str: ...


@overload
def get_env(name: str, default: None = None) -> str | None: ...


def get_env(name: str, default: str | None = None) -> str | None:
    """Return an environment variable stripped of surrounding whitespace.

    A variable that is unset and one holding nothing but whitespace are treated
    alike: both give the default. An all-whitespace value is never what anyone
    meant, and letting it through only moves the failure somewhere less obvious.
    """
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip() or default


GROQ_API_KEY = get_env("GROQ_API_KEY")
GROQ_MODEL = get_env("GROQ_MODEL", DEFAULT_GROQ_MODEL)
USER_AGENT = get_env("USER_AGENT", DEFAULT_USER_AGENT)


# --- Rickshaw pricing policy -------------------------------------------------
#
# PROVISIONAL. Every number below is a starting point for the project owner to
# tune, not a measured market rate.
#
# These constants encode a living wage floor for rickshaw pullers, not just a
# market price. That distinction is the whole point of the block. A market rate
# is whatever a passenger can get a tired puller to accept at the end of a long
# day; the floor is what this app will recommend regardless. The FLOOR_PER_KM
# values and FARE_ABSOLUTE_MIN_BDT are therefore deliberate policy, and
# fare_calculator applies them *after* crowdsourced data has had its say — a
# pile of low submissions is evidence that haggling works, not evidence that a
# fare is fair.
#
# Deliberately plain constants rather than get_env values, which is an exception
# to the rule the rest of this file exists to enforce. They are one policy, not
# twelve settings: the floor only means anything relative to the fair rate, and
# the trust thresholds only mean anything relative to each other. Making them
# individually editable from a dashboard would allow a floor above the fair rate
# with nobody reviewing the combination. Changing pricing should cost a commit.

FARE_BASE_BDT = 20  # per-trip flag, charged at any distance
FARE_PER_KM_PEDAL = 25  # fair rate, pedal rickshaw
FARE_PER_KM_BATTERY = 20  # fair rate, battery rickshaw

# Never recommend below these, whatever the crowd says.
FARE_FLOOR_PER_KM_PEDAL = 18
FARE_FLOOR_PER_KM_BATTERY = 15
FARE_ABSOLUTE_MIN_BDT = 30

# Beyond the threshold, the *excess* distance is charged at the multiplier —
# a rickshaw puller's effort per kilometre is not constant over a long trip.
LONG_TRIP_THRESHOLD_KM = 8.0
LONG_TRIP_MULTIPLIER = 1.3

# Fares here are a negotiation, not a tariff, so a recommendation is a band
# around a midpoint rather than a single number to be argued down from.
FARE_RANGE_SPREAD = 0.15

# How much crowdsourced data it takes to be believed. Below MIN_TRUST a handful
# of submissions is noise; above FULL_TRUST it is better evidence of the local
# going rate than any formula here. Between them the two are blended.
CROWDSOURCE_MIN_TRUST = 5
CROWDSOURCE_FULL_TRUST = 20

# Stamped so a fare quoted in a screenshot can be dated. Fuel, rice and rent all
# move; a rate card with no date on it is a rate card nobody dares change.
FARE_RATES_EFFECTIVE_DATE = "2026-08"
