from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from collections import deque
import httpx
import os
import json  # 💡 Cleanly imported at the top now
import logging
import threading
import time
from dotenv import load_dotenv
from groq import Groq
from database import init_db, get_connection
import math

load_dotenv()

logger = logging.getLogger(__name__)

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

app = FastAPI()

# (distance_km, min_taka_per_km, max_taka_per_km). The per-km rate climbs with
# distance because a rickshaw puller's fatigue premium grows on longer trips,
# and the longest trips are really roaming/hourly bookings rather than A-to-B.
#
# Rates are interpolated *between* anchors rather than applied as flat bands, so
# the bounds are continuous in distance. The earlier banded version jumped from
# 30-40 Tk/km at 12.0 km straight to 50-120 Tk/km at 12.01 km, which meant a
# fare accepted at 12 km was rejected at 12.1 km.
FARE_RATE_ANCHORS: list[tuple[float, float, float]] = [
    (0.0, 20.0, 35.0),
    (5.0, 20.0, 35.0),
    (12.0, 30.0, 55.0),
    (20.0, 35.0, 80.0),
    (40.0, 40.0, 110.0),
]

# Dhaka rickshaws charge a minimum flag fare no matter how short the hop is, so
# a plain per-km rate under-prices very short trips (0.3 km x 30 = 9 Tk, which
# would reject the 30 Tk a puller actually charges).
MIN_PLAUSIBLE_FARE = 20.0
MIN_PLAUSIBLE_CEILING = 40.0


def calculate_logical_bounds(distance_km: float) -> tuple[float, float]:
    """Return the (min, max) plausible fare in BDT for a trip of this length."""
    first_km, first_min_rate, first_max_rate = FARE_RATE_ANCHORS[0]
    last_km, last_min_rate, last_max_rate = FARE_RATE_ANCHORS[-1]

    if distance_km <= first_km:
        min_rate, max_rate = first_min_rate, first_max_rate
    elif distance_km >= last_km:
        min_rate, max_rate = last_min_rate, last_max_rate
    else:
        min_rate, max_rate = last_min_rate, last_max_rate
        for (lo_km, lo_min, lo_max), (hi_km, hi_min, hi_max) in zip(
            FARE_RATE_ANCHORS, FARE_RATE_ANCHORS[1:]
        ):
            if lo_km <= distance_km <= hi_km:
                ratio = (distance_km - lo_km) / (hi_km - lo_km)
                min_rate = lo_min + (hi_min - lo_min) * ratio
                max_rate = lo_max + (hi_max - lo_max) * ratio
                break

    return (
        max(distance_km * min_rate, MIN_PLAUSIBLE_FARE),
        max(distance_km * max_rate, MIN_PLAUSIBLE_CEILING),
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

@app.on_event("startup")
def startup():
    init_db()

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

    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        data = response.json()

    if data["code"] != "Ok":
        raise HTTPException(status_code=400, detail="Route not found")

    route = data["routes"][0]

    return {
        "coordinates": route["geometry"]["coordinates"],
        "distance": route["distance"],
        "duration": route["duration"],
    }


class FareSubmission(BaseModel):
    distance_km: float
    fare_amount: float
    route_type: str


@app.post("/fares", dependencies=[Depends(enforce_fare_rate_limit)])
def submit_fare(submission: FareSubmission):
    if submission.distance_km <= 0 or submission.fare_amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid distance or fare amount.")
        
    min_logical, max_logical = calculate_logical_bounds(submission.distance_km)
    
    # Pre-filter out completely unhinged submissions (e.g. 50 Tk for 30km or 10,000 Tk for 2km)
    if submission.fare_amount < (min_logical * 0.5) or submission.fare_amount > (max_logical * 2.0):
        raise HTTPException(
            status_code=400, 
            detail="Submission rejected. The fare entered is outside a realistic range for this distance."
        )

    
    # 2. AI RESEARCH & VALIDATION PROMPT (Deep Context Verification)
    validation_prompt = f"""You are a strict data validation assistant for Dhaka transport metrics.
Your job is to determine if a crowdsourced fare submission is realistic or if it's fake/spam.

Trip Parameters:
- Distance: {submission.distance_km} km
- Mode of Travel: {submission.route_type}
- Fare Submitted by User: ৳{submission.fare_amount} BDT

System Reference Benchmarks:
- For this specific distance, a realistic fare fallback window is between ৳{round(min_logical, 2)} and ৳{round(max_logical, 2)} BDT.
- Consider context: A manual rickshaw requires significant human physical exertion over {submission.distance_km} km, meaning fair demand/fatigue premiums or bad weather inflation can naturally push the fare towards the mid-to-higher end of the window.
- Reject only if the value is completely unhinged spam (e.g., trying to pay ৳50 for 20 km, or ৳2000 for 2 km).

Evaluate the authenticity. Respond strictly in JSON format matching this schema:
{{
  "is_valid": true or false,
  "reason": "A one-sentence explanation in English explaining why the fare is fair or fake."
}}
Do not write any introductory or trailing text outside of the JSON block."""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": validation_prompt}],
            max_tokens=100,
            temperature=0.1, 
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
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO fare_submissions (distance_km, fare_amount, route_type) VALUES (?, ?, ?)",
        (submission.distance_km, submission.fare_amount, submission.route_type),
    )
    conn.commit()
    conn.close()
    
    return {"message": "Thank you! Your verified fare submission has been saved to help other commuters."}


@app.get("/fares/average")
def get_average_fare(distance_km: float, route_type: str):
    min_dist = distance_km - 0.5
    max_dist = distance_km + 0.5

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT AVG(fare_amount), COUNT(*)
        FROM fare_submissions
        WHERE distance_km BETWEEN ? AND ?
        AND route_type = ?
        """,
        (min_dist, max_dist, route_type),
    )
    avg_fare, count = cursor.fetchone()
    conn.close()

    return {
        "average_fare": round(avg_fare, 2) if avg_fare else None,
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

    headers = {
        "User-Agent": "DhakaRouteApp/1.0"
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, headers=headers)
        data = response.json()

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


@app.get("/reverse-geocode")
async def reverse_geocode(lat: float, lng: float):
    url = "https://nominatim.openstreetmap.org/reverse"

    params = {
        "lat": lat,
        "lon": lng,
        "format": "json",
    }

    headers = {
        "User-Agent": "DhakaRouteApp/1.0"
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, headers=headers)
        data = response.json()

    if "error" in data:
        return {"name": f"{lat:.4f}, {lng:.4f}"}

    address = data.get("address", {})
    name = (
        address.get("road") or
        address.get("neighbourhood") or
        address.get("suburb") or
        address.get("town") or
        address.get("city") or
        data.get("display_name", f"{lat:.4f}, {lng:.4f}")
    )

    return {"name": name}

@app.get("/ai-fare-recommendation")
async def ai_fare_recommendation(
    distance_km: float,
    route_type: str,
    area: str = "Dhaka",
):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT AVG(fare_amount), COUNT(*), MIN(fare_amount), MAX(fare_amount)
        FROM fare_submissions
        WHERE distance_km BETWEEN ? AND ?
        AND route_type = ?
        """,
        (distance_km - 0.5, distance_km + 0.5, route_type),
    )
    avg_fare, count, min_fare, max_fare = cursor.fetchone()
    conn.close()

    fare_context = (
        f"Crowdsourced data from {count} trips: "
        f"average ৳{round(avg_fare, 0)}, "
        f"range ৳{min_fare}–৳{max_fare}"
        if count and count > 0
        else "No crowdsourced fare data available yet."
    )

    if distance_km > 10.0:
        roaming_instruction = """
        IMPORTANT CRITICAL EXTRA DIRECTION:
        This trip is exceptionally long (over 10 km). In Dhaka, a point-to-point rickshaw trip is rarely this long. 
        Assume the user wants to roam around the city, take a scenic route, or book the rickshaw for a long time. 
        - Do NOT calculate using basic low rates (e.g., 200 Tk is too low for 17 km).
        - Recommend a significantly higher premium total (e.g., 500-800+ Tk) or explicitly advise bargaining for an hourly rate (e.g., 150-200 Tk per hour) because pulling a rickshaw for this distance requires immense physical effort.
        """
    else:
        roaming_instruction = "Give a standard fair price suggestion based on typical Dhaka rickshaw rates (roughly 20-25 Tk per km depending on the area)."

    prompt = f"""You are a helpful Dhaka transport assistant.
Give a short, friendly rickshaw fare recommendation in Bengali (বাংলা) language only.

Trip details:
- Distance: {distance_km} km
- Transport: {route_type}
- Area: {area}, Dhaka, Bangladesh
- {fare_context}

{roaming_instruction}

Give a recommended fare range in BDT and one bargaining tip.
CRITICAL INSTRUCTION: Your entire response MUST be exactly 3 or 4 sentences long. Do not write less than 3 sentences, and do not write more than 4 sentences. Make sure the final sentence is complete. Write only in Bengali."""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024, 
            temperature=0.3,
        )
        recommendation = response.choices[0].message.content
        return {"recommendation": recommendation}
    except Exception:
        # Logged server-side rather than returned: the raw exception can name
        # internal config and credential state, and it reaches the user's screen.
        logger.exception("AI fare recommendation failed")
        return {
            "recommendation": "এই মুহূর্তে পরামর্শ তৈরি করা যাচ্ছে না। একটু পরে আবার চেষ্টা করুন।"
        }
