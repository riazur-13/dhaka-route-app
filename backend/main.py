from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from collections import deque
from contextlib import asynccontextmanager
import httpx
import json
import logging
import threading
import time
from typing import Literal
from groq import Groq
from config import BOUNDS_WIDENING_FACTOR, GROQ_API_KEY, GROQ_MODEL, USER_AGENT
from fare_calculator import (
    calculate_fare,
    round_fare_for_display,
    round_fare_nearest,
)
from database import (
    cache_place_failure,
    cache_place_name,
    close_pool,
    db_cursor,
    init_db,
    lookup_place_name,
)

logger = logging.getLogger(__name__)

groq_client = Groq(api_key=GROQ_API_KEY)

# Nominatim and OSRM are free public services with no SLA behind them. httpx
# defaults to five seconds for every phase; the read budget is raised because a
# slow answer still beats no answer, while connect is kept short because a host
# that is refusing us fails at connect and there is nothing there to wait for.
UPSTREAM_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# The Groq SDK's own default is ten minutes. /fares is a sync `def`, so FastAPI
# runs it in a worker thread from a finite pool — one wedged completion would
# hold a thread for all ten of those minutes.
GROQ_TIMEOUT_SECONDS = 30.0

# Enough of a failing response to recognise what it is — a Nominatim block page,
# an OSRM rate-limit notice, some proxy's HTML — without pouring an entire
# document into the log on every failed request.
UPSTREAM_BODY_LOG_CHARS = 200


async def fetch_upstream_json(
    url: str, *, service: str, params: dict | None = None
) -> object:
    """GET `url` and return its parsed JSON, or raise 502 with the reason logged.

    Three separate things can go wrong here and all three used to reach the
    browser as a 500. The request may never get an answer at all (timeout, DNS,
    connection reset); the answer may carry an error status; or it may carry a
    perfectly good 200 with a body that is not JSON — which is what a block page
    is, and what took /reverse-geocode down. .json() was called on HTML and the
    JSONDecodeError went straight past FastAPI to the client.

    The response body is logged and never returned: an upstream error page can
    name our egress IP or echo the query, and the caller only needs to know that
    the service is down, not how.
    """
    unavailable = f"{service} is unavailable right now. Please try again in a moment."

    try:
        async with httpx.AsyncClient(
            timeout=UPSTREAM_TIMEOUT, headers={"User-Agent": USER_AGENT}
        ) as client:
            response = await client.get(url, params=params)
    except httpx.RequestError as exc:
        logger.warning("%s could not be reached: %r", service, exc)
        raise HTTPException(status_code=502, detail=unavailable) from exc

    if response.status_code != 200:
        logger.warning(
            "%s returned HTTP %s: %s",
            service,
            response.status_code,
            response.text[:UPSTREAM_BODY_LOG_CHARS],
        )
        raise HTTPException(status_code=502, detail=unavailable)

    try:
        return response.json()
    except ValueError as exc:
        logger.warning(
            "%s returned HTTP 200 with a body that is not JSON: %s",
            service,
            response.text[:UPSTREAM_BODY_LOG_CHARS],
        )
        raise HTTPException(status_code=502, detail=unavailable) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Deliberately not guarded by a try: if the schema cannot be created the
    # service should refuse to start, rather than come up and return 500s on
    # every fare submission.
    init_db()
    yield
    close_pool()


app = FastAPI(lifespan=lifespan)

# Dhaka rickshaws charge a minimum flag fare no matter how short the hop is, so
# a plain per-km rate under-prices very short trips (0.3 km x 30 = 9 Tk, which
# would reject the 30 Tk a puller actually charges).
MIN_PLAUSIBLE_FARE = 20.0
MIN_PLAUSIBLE_CEILING = 40.0


def calculate_logical_bounds(
    distance_km: float, vehicle_type: str = "pedal"
) -> tuple[float, float]:
    """The window a submitted fare has to fall inside to be believable.

    Derived from the same rate card the app recommends from, rather than from a
    second table of its own. It had a second table — FARE_RATE_ANCHORS — and the
    two disagreed: a 7.3 km battery trip was advised at 141-191 and then
    rejected at 150, because the anchors were pedal-shaped and put the lower
    bound at 170. The app recommended a fare and refused it in the same breath.
    One source of truth is the fix; everything else here is detail.

    Widened from the recommended band because these two things are asked
    different questions. The band answers "what should this cost", and is
    deliberately narrow. This answers "could anyone have actually paid that",
    and a window as tight as the band calls every real-world variation a lie.
    See BOUNDS_WIDENING_FACTOR in config.py for why the factor is what it is.

    The short-trip floors stay. A flag fare is charged whatever the distance, so
    without them a 0.1 km hop would accept 10 Tk and reject the 30 a puller
    charges — the bug MIN_PLAUSIBLE_FARE was added for in the first place.
    """
    fare = calculate_fare(
        distance_km=distance_km,
        vehicle_type=vehicle_type,
        crowd_median=None,
        crowd_count=0,
    )

    return (
        max(fare["low"] / BOUNDS_WIDENING_FACTOR, MIN_PLAUSIBLE_FARE),
        max(fare["high"] * BOUNDS_WIDENING_FACTOR, MIN_PLAUSIBLE_CEILING),
    )


# Every accepted /fares submission costs a Groq completion, so the endpoint is
# throttled on two axes: a per-client window for fairness, and a global window
# that caps total spend even if the per-client key is being gamed.
#
# State lives in process memory because the free Render tier runs a single
# instance with nothing shared to put it in. It resets on redeploy, which is
# acceptable — the goal is to stop a loop from draining the Groq quota, not to
# meter usage precisely.
PER_CLIENT_MAX_SUBMISSIONS = 5
PER_CLIENT_WINDOW_SECONDS = 60.0
GLOBAL_MAX_SUBMISSIONS = 60
GLOBAL_WINDOW_SECONDS = 60.0
MAX_TRACKED_CLIENTS = 2048

GLOBAL_BUCKET = "__global__"
rate_limit_buckets: dict[str, deque[float]] = {}
rate_limit_lock = threading.Lock()


def client_key(request: Request) -> str:
    # Render terminates TLS at a proxy, so the socket peer is the proxy rather
    # than the user — without this every visitor would share one bucket. The
    # left-most X-Forwarded-For entry is the original client. It is caller-
    # supplied and therefore spoofable, which is exactly why the global cap
    # below exists as a backstop.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def window_retry_after(key: str, max_hits: int, window: float, now: float) -> float | None:
    """Seconds until `key` frees a slot, or None if it has one now.

    Callers must hold rate_limit_lock.
    """
    hits = rate_limit_buckets.get(key)
    if not hits:
        return None

    cutoff = now - window
    while hits and hits[0] < cutoff:
        hits.popleft()

    if len(hits) >= max_hits:
        return max(hits[0] - cutoff, 1.0)
    return None


def prune_rate_limit_buckets(now: float) -> None:
    """Drop buckets no longer inside any window. Callers must hold the lock."""
    if len(rate_limit_buckets) <= MAX_TRACKED_CLIENTS:
        return

    cutoff = now - max(PER_CLIENT_WINDOW_SECONDS, GLOBAL_WINDOW_SECONDS)
    stale = [
        key
        for key, hits in rate_limit_buckets.items()
        if key != GLOBAL_BUCKET and (not hits or hits[-1] < cutoff)
    ]
    for key in stale:
        del rate_limit_buckets[key]


def enforce_fare_rate_limit(request: Request) -> None:
    key = client_key(request)
    now = time.monotonic()

    with rate_limit_lock:
        prune_rate_limit_buckets(now)

        retry_after = window_retry_after(
            key, PER_CLIENT_MAX_SUBMISSIONS, PER_CLIENT_WINDOW_SECONDS, now
        )
        if retry_after is None:
            retry_after = window_retry_after(
                GLOBAL_BUCKET, GLOBAL_MAX_SUBMISSIONS, GLOBAL_WINDOW_SECONDS, now
            )

        if retry_after is not None:
            seconds = int(retry_after) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Too many fare submissions. Please wait {seconds} seconds and try again.",
                headers={"Retry-After": str(seconds)},
            )

        # Only charge the buckets once the request is actually going through.
        rate_limit_buckets.setdefault(key, deque()).append(now)
        rate_limit_buckets.setdefault(GLOBAL_BUCKET, deque()).append(now)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Touches nothing: no database, no outbound call, no work of any kind. That is
# the whole specification, and it is what makes the `async def` safe — see the
# ASYNC_ALLOWED entry in tests/test_endpoint_concurrency.py. Answering on the
# event loop rather than from the worker pool is deliberate here: the moment you
# most want a health check to reply is when every worker thread is tied up, and
# that is exactly when a plain `def` would queue behind them.
#
# The frontend pings this on mount so Render's free tier starts waking the
# container before the user's first click, which otherwise pays the entire cold
# start with no feedback. Any request would wake it, a 404 included; this exists
# so the wake-up is a deliberate call rather than a side effect of asking for
# something that is not there, and so there is somewhere to put a real
# readiness check later if one is ever wanted.
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/route")
async def get_route(
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
):
    url = (
        f"https://router.project-osrm.org/route/v1/foot/"
        f"{start_lng},{start_lat};{end_lng},{end_lat}"
        f"?overview=full&geometries=geojson"
    )

    data = await fetch_upstream_json(url, service="OSRM routing")

    # .get rather than ["code"]: a JSON body that parsed fine but is not the
    # shape OSRM documents is still an upstream problem, and a KeyError here
    # would have been another 500.
    if not isinstance(data, dict) or data.get("code") != "Ok":
        raise HTTPException(status_code=400, detail="Route not found")

    routes = data.get("routes") or []
    if not routes:
        raise HTTPException(status_code=400, detail="Route not found")

    route = routes[0]

    return {
        "coordinates": route["geometry"]["coordinates"],
        "distance": route["distance"],
        "duration": route["duration"],
    }


class FareSubmission(BaseModel):
    distance_km: float
    fare_amount: float
    route_type: str
    # Literal, so Pydantic rejects anything else with a 422 before the value
    # reaches Postgres. The CHECK constraint on the column is a backstop for
    # writes that do not come through this model, not the primary guard — a
    # constraint violation surfacing here would be a 500, which is the wrong
    # answer to a client sending a bad field.
    #
    # Required, with no default. 'unknown' is a truthful label for the rows
    # that predate the column and a lie for anything written after it, and a
    # mislabelled row cannot be corrected later because only the passenger ever
    # knew which vehicle they rode.
    vehicle_type: Literal["pedal", "battery"]


@app.post("/fares", dependencies=[Depends(enforce_fare_rate_limit)])
def submit_fare(submission: FareSubmission):
    if submission.distance_km <= 0 or submission.fare_amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid distance or fare amount.")
        
    # Vehicle-aware, which it was not: the bounds were pedal-shaped for every
    # submission, so a battery fare inside its own recommended range was judged
    # against a pedal window and rejected as spam. Both Groq-failure fallbacks
    # below compare against these same two numbers, so they are corrected too.
    min_logical, max_logical = calculate_logical_bounds(
        submission.distance_km, submission.vehicle_type
    )
    
    # Pre-filter out completely unhinged submissions (e.g. 50 Tk for 30km or 10,000 Tk for 2km)
    if submission.fare_amount < (min_logical * 0.5) or submission.fare_amount > (max_logical * 2.0):
        raise HTTPException(
            status_code=400, 
            detail="Submission rejected. The fare entered is outside a realistic range for this distance."
        )


    # The prompt used to assert "a manual rickshaw requires significant human
    # physical exertion" for every submission. Two things were wrong with that.
    # It is simply false for a battery rickshaw, where a motor does the work.
    # And it told the model to lean high inside a window that was already
    # pedal-shaped, so a battery fare was pushed up twice over before being
    # judged too low. Describe the vehicle that was actually ridden instead.
    if submission.vehicle_type == "battery":
        vehicle_description = "battery-powered (motorised) rickshaw"
        vehicle_context = (
            f"A battery rickshaw carries the rider {submission.distance_km} km under motor "
            "power, so it is normally cheaper than a pedal rickshaw over the same distance "
            "and there is no fatigue premium to allow for. Weather and demand can still "
            "raise it, but expect fares around the middle of the window."
        )
    else:
        vehicle_description = "pedal (manually pulled) rickshaw"
        vehicle_context = (
            f"A pedal rickshaw requires significant human physical exertion over "
            f"{submission.distance_km} km, so fatigue premiums, demand and bad weather can "
            "naturally push the fare toward the mid-to-higher end of the window."
        )

    # 2. AI RESEARCH & VALIDATION PROMPT (Deep Context Verification)
    validation_prompt = f"""You are a strict data validation assistant for Dhaka transport metrics.
Your job is to determine if a crowdsourced fare submission is realistic or if it's fake/spam.

Trip Parameters:
- Distance: {submission.distance_km} km
- Mode of Travel: {submission.route_type}
- Vehicle: {vehicle_description}
- Fare Submitted by User: ৳{submission.fare_amount} BDT

System Reference Benchmarks:
- For this distance on this vehicle, a realistic fare window is ৳{round(min_logical)} to ৳{round(max_logical)} BDT. This window is derived from the same rate card the app recommends from, so a fare the app itself suggested is always inside it.
- Consider context: {vehicle_context}
- Reject only if the value is completely unhinged spam (e.g., trying to pay ৳50 for 20 km, or ৳2000 for 2 km).

Evaluate the authenticity. Respond strictly in JSON format matching this schema:
{{
  "is_valid": true or false,
  "reason": "A one-sentence explanation in English explaining why the fare is fair or fake."
}}
Do not write any introductory or trailing text outside of the JSON block."""

    try:
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": validation_prompt}],
            # Was 100, which is not survivable on a reasoning model: the
            # reasoning tokens are billed against this budget and land before
            # any JSON does, so the response came back empty and Groq rejected
            # it with json_validate_failed on every single submission. That 400
            # is caught below and falls back to the range check, so the endpoint
            # went on returning 200 with the AI silently skipped. Measured usage
            # on this prompt is ~160-190 tokens; the headroom is deliberate,
            # because the failure mode here is invisible rather than loud.
            max_tokens=1024,
            temperature=0.1,
            timeout=GROQ_TIMEOUT_SECONDS,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        
        if not content:
            raise HTTPException(status_code=500, detail="AI backend returned an empty response.")
            
        result_data = json.loads(content)
        
        # 3. IF AI DETECTS ANOMALY / FAKE USER -> REJECT IT
        if not result_data.get("is_valid", True):
            raise HTTPException(
                status_code=400, 
                detail=f"AI Validation Failed: {result_data.get('reason', 'Unrealistic data entry detected.')}"
            )

    except json.JSONDecodeError:
        # If the LLM output is not valid JSON, we fall back to a safe backup range-check check
        logger.warning("Groq validation returned non-JSON output; falling back to range check")
        if not (min_logical <= submission.fare_amount <= max_logical):
            raise HTTPException(status_code=400, detail="Fare entry validation failed JSON structuring.")

    except HTTPException as he:
        # Pass our intentional custom HTTP exceptions straight through
        raise he
    except Exception:
        # System fallback fallback safety rule
        logger.exception("Groq fare validation call failed; falling back to range check")
        if not (min_logical <= submission.fare_amount <= max_logical):
            raise HTTPException(status_code=400, detail="Fare value evaluation failed structural checks.")

    # 4. DATA SAVED ONLY IF VALIDATION CHECKS PASS SUCCESSFULLY
    with db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO fare_submissions (distance_km, fare_amount, route_type, vehicle_type)"
            " VALUES (%s, %s, %s, %s)",
            (
                submission.distance_km,
                submission.fare_amount,
                submission.route_type,
                submission.vehicle_type,
            ),
        )

    return {"message": "Thank you! Your verified fare submission has been saved to help other commuters."}


@app.get("/fares/average")
def get_average_fare(distance_km: float, route_type: str, vehicle_type: str = "pedal"):
    if vehicle_type not in ("pedal", "battery"):
        raise HTTPException(
            status_code=400, detail="vehicle_type must be 'pedal' or 'battery'."
        )

    min_dist = distance_km - 0.5
    max_dist = distance_km + 0.5

    # Scoped to one vehicle for the same reason /ai-fare-recommendation is: a
    # battery rickshaw is priced below a pedal one deliberately, so an average
    # over both sits between two rates and describes neither. This is the figure
    # the app labels "Average fare" on screen, which makes it the one a rider
    # would actually quote at a puller — the mixed version was understating the
    # pedal rate to the person doing the pedalling.
    #
    # Defaulted rather than required, matching the recommendation endpoint. A
    # default is safe here in a way it is not on /fares: this reads, it does not
    # write, so a wrong guess shows a number for the wrong vehicle for a moment
    # rather than putting one in the table permanently.
    #
    # 'unknown' rows fall out on their own, since the parameter is only ever
    # 'pedal' or 'battery' by this point.
    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT AVG(fare_amount), COUNT(*)
            FROM fare_submissions
            WHERE distance_km BETWEEN %s AND %s
            AND route_type = %s
            AND vehicle_type = %s
            """,
            (min_dist, max_dist, route_type, vehicle_type),
        )
        # An aggregate always returns exactly one row, even over no data — the
        # default is only here to satisfy fetchone()'s Optional return type.
        avg_fare, count = cursor.fetchone() or (None, 0)

    return {
        # Rounded for display only; the stored submissions keep full precision.
        # Nearest rather than up or down, because an average describes what
        # people paid rather than bounding what they should — neither direction
        # protects anything here, so the least distorting rule wins.
        "average_fare": round_fare_nearest(avg_fare) if avg_fare else None,
        "submission_count": count,
    }


@app.get("/search")
async def search_place(query: str):
    full_query = f"{query}, Dhaka, Bangladesh"

    url = "https://nominatim.openstreetmap.org/search"

    params = {
        "q": full_query,
        "format": "json",
        "limit": 5,
        "countrycodes": "bd",
        "accept-language": "en",
        "dedupe": 1,
    }

    data = await fetch_upstream_json(
        url, service="Nominatim place search", params=params
    )

    # A successful search is a JSON array. Nominatim reports its own errors as
    # an object instead, and iterating one of those yields its keys as strings —
    # which reached place["display_name"] and raised TypeError as a 500.
    if not isinstance(data, list):
        logger.warning("Nominatim place search returned %s, not a list", type(data).__name__)
        raise HTTPException(
            status_code=502,
            detail="Place search is unavailable right now. Please try again in a moment.",
        )

    results = [
        {
            "name": ", ".join(place["display_name"].split(", ")[:3]),
            "full_name": place["display_name"],
            "lat": float(place["lat"]),
            "lng": float(place["lon"]),
        }
        for place in data
    ]

    return {"results": results}


REVERSE_GEOCODE_UNAVAILABLE = (
    "Place names are unavailable right now. Please try again in a few minutes."
)


@app.get("/reverse-geocode")
async def reverse_geocode(lat: float, lng: float):
    coordinate_name = f"{lat:.4f}, {lng:.4f}"

    # run_in_threadpool because psycopg is synchronous and this endpoint is not:
    # called directly, each of these three round trips to Neon would block the
    # event loop, and with it every other request in the process. Same reasoning
    # as the note above /ai-fare-recommendation, arrived at from the other side.
    cached = await run_in_threadpool(lookup_place_name, lat, lng)
    if cached is not None:
        # A cached None means the last attempt at this spot failed upstream.
        # Answering from that is the whole point: a user clicking a blocked
        # location five times should cost Nominatim nothing after the first.
        if cached.name is None:
            raise HTTPException(status_code=502, detail=REVERSE_GEOCODE_UNAVAILABLE)
        return {"name": cached.name}

    url = "https://nominatim.openstreetmap.org/reverse"

    params = {
        "lat": lat,
        "lon": lng,
        "format": "json",
    }

    try:
        data = await fetch_upstream_json(
            url, service="Nominatim reverse geocoding", params=params
        )
    except HTTPException:
        await run_in_threadpool(cache_place_failure, lat, lng)
        raise

    if not isinstance(data, dict):
        logger.warning("Nominatim reverse geocoding returned %s, not an object", type(data).__name__)
        await run_in_threadpool(cache_place_failure, lat, lng)
        raise HTTPException(status_code=502, detail=REVERSE_GEOCODE_UNAVAILABLE)

    if "error" in data:
        # Not a failure — this is Nominatim answering. There is genuinely no
        # address at this point (open water, a field), so the coordinates are
        # the honest name, and that fact is as durable as any other name here.
        name = coordinate_name
    else:
        address = data.get("address", {})
        name = (
            address.get("road") or
            address.get("neighbourhood") or
            address.get("suburb") or
            address.get("town") or
            address.get("city") or
            data.get("display_name", coordinate_name)
        )

    await run_in_threadpool(cache_place_name, lat, lng, name)

    return {"name": name}

# Deliberately `def`, not `async def`. Everything below it blocks: the Postgres
# round trip and the Groq completion are both synchronous, and the completion can
# take seconds. Declared async they would run *on* the event loop and stall every
# other request in the process for that whole time — including /route and /search,
# which have no reason to wait on a language model. As a plain `def`, FastAPI runs
# it in a worker thread and the loop stays free.
#
# This was survivable when the query hit a local SQLite file; against a database
# in another region it is not.
@app.get("/ai-fare-recommendation")
def ai_fare_recommendation(
    distance_km: float,
    route_type: str,
    area: str = "Dhaka",
    vehicle_type: str = "pedal",
):
    if vehicle_type not in ("pedal", "battery"):
        raise HTTPException(
            status_code=400, detail="vehicle_type must be 'pedal' or 'battery'."
        )

    # vehicle_type is only ever 'pedal' or 'battery' by the time it gets here,
    # so the equality drops every 'unknown' row on the floor. That is the point:
    # those are the submissions from before the column existed, and a fare whose
    # vehicle nobody recorded is evidence about neither rate. Better to fall back
    # to the rules-based fare than to quote a number built from a mixture.
    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT AVG(fare_amount), COUNT(*)
            FROM fare_submissions
            WHERE distance_km BETWEEN %s AND %s
            AND route_type = %s
            AND vehicle_type = %s
            """,
            (distance_km - 0.5, distance_km + 0.5, route_type, vehicle_type),
        )
        avg_fare, count = cursor.fetchone() or (None, 0)

    # Named crowd_median because that is what it should be, and will be: an
    # average is dragged around by one absurd submission in a way a median is
    # not, and a fare table is exactly where absurd submissions land. Swapping
    # the aggregate is a separate task, so for now the calculator is handed an
    # average under the name of a median. This comment is the honest bit.
    fare = calculate_fare(
        distance_km=distance_km,
        vehicle_type=vehicle_type,
        crowd_median=float(avg_fare) if avg_fare is not None else None,
        crowd_count=count or 0,
    )

    # The whole point of the rewrite: the number is already decided by the time
    # the model is asked anything. Every pricing instruction that used to live
    # in this prompt — the per-km rates, the over-10-km roaming premium — is now
    # in config.py and fare_calculator.py, where it can be tested and reviewed.
    # Groq's only remaining job is to say it in Bengali.
    # Rounded at the edge, not in fare_calculator: the exact figures are what the
    # plausibility bounds and the labour floor are checked against, and a lossy
    # number upstream of those checks would be a number nothing could verify.
    #
    # Both ends floor to tens, except where that would drop the low end below
    # the vehicle's labour floor — see round_fare_for_display for why, and why
    # the high end follows it when that happens.
    #
    # Assigned once, here, above everything that reads it. The prompt below and
    # the payload further down are two consumers of one value, and the visible
    # bug this fixes was the model being handed unrounded figures and writing
    # them into the Bengali sentence while the JSON fields were correct. Keep
    # these two lines and their readers in this order.
    display_low, display_high = round_fare_for_display(
        fare["low"], fare["high"], distance_km, vehicle_type
    )

    if fare["floor_applied"]:
        tone = (
            "This range sits at the fair minimum for the labour involved. "
            "Word it so the passenger understands this is already a fair price "
            "to the puller, and should not be bargained down further."
        )
    else:
        tone = "Include one practical bargaining tip."

    prompt = f"""You are a helpful Dhaka transport assistant.
Write a short, friendly note in Bengali (বাংলা) language only.

The fare has already been calculated. Do not change it, do not recalculate it,
and do not suggest any other number.

- Distance: {distance_km} km
- Area: {area}, Dhaka, Bangladesh
- Recommended fare: ৳{display_low} to ৳{display_high} BDT

{tone}

CRITICAL INSTRUCTION: Your entire response MUST be exactly 3 or 4 sentences long.
Do not write less than 3 sentences, and do not write more than 4 sentences. Make
sure the final sentence is complete. State the fare range exactly as given above.
Write only in Bengali."""

    # Built before the Groq call so the numbers survive it. The fare is the
    # answer; the Bengali is the wrapper, and a missing wrapper is not a missing
    # answer. The frontend can render the range on its own.
    payload = {
        "fare_low": display_low,
        "fare_high": display_high,
        "source": fare["source"],
        "sample_size": fare["sample_size"],
        "floor_applied": fare["floor_applied"],
    }

    fallback = "এই মুহূর্তে পরামর্শ তৈরি করা যাচ্ছে না। একটু পরে আবার চেষ্টা করুন।"

    try:
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            # Same reasoning-token budget problem as the validation call, plus
            # Bengali runs to more tokens per sentence than English. Measured
            # 390-550 tokens for the 3-4 sentences this prompt asks for, so 1024
            # was close enough to the ceiling to truncate mid-sentence.
            max_tokens=2048,
            temperature=0.3,
            timeout=GROQ_TIMEOUT_SECONDS,
        )
        recommendation = response.choices[0].message.content

        # A successful call can still carry no text. gpt-oss-20b is a reasoning
        # model, and reasoning tokens are billed against max_tokens and emitted
        # before any content, so hitting the ceiling returns HTTP 200 with
        # content=None; a safety filter does the same. This used to fall
        # straight through and serve {"recommendation": null} with a 200 and
        # nothing in the log. An empty answer is a failed answer.
        if not recommendation or not recommendation.strip():
            logger.warning(
                "Groq returned an empty recommendation (finish_reason=%s)",
                getattr(response.choices[0], "finish_reason", "unknown"),
            )
            return {**payload, "recommendation": fallback, "recommendation_available": False}

        return {
            **payload,
            "recommendation": recommendation.strip(),
            "recommendation_available": True,
        }
    except Exception:
        # Logged server-side rather than returned: the raw exception can name
        # internal config and credential state, and it reaches the user's screen.
        logger.exception("AI fare recommendation failed")
        return {**payload, "recommendation": fallback, "recommendation_available": False}
