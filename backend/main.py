from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import os
import json  # 💡 Cleanly imported at the top now
from dotenv import load_dotenv
from groq import Groq
from database import init_db, get_connection
import math

load_dotenv()

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

app = FastAPI()

def calculate_logical_bounds(distance_km: float) -> tuple[float, float]:
    if distance_km <= 5.0:
        # Standard: 35-55 Tk per Km
        return (distance_km * 25, distance_km * 65)
    elif 5.0 < distance_km <= 12.0:
        # Medium distance fatigue premium
        return (distance_km * 35, distance_km * 85)
    else:
        # Extreme distances (30km+ roaming packages)
        return (distance_km * 50, distance_km * 120)

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


@app.post("/fares")
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
        if not (min_logical <= submission.fare_amount <= max_logical):
            raise HTTPException(status_code=400, detail="Fare entry validation failed JSON structuring.")
   
    except HTTPException as he:
        # Pass our intentional custom HTTP exceptions straight through
        raise he
    except Exception as e:
        # System fallback fallback safety rule
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
Make sure your response is a completely finished paragraph. Do not leave the last sentence incomplete or cut off mid-way. Write only in Bengali."""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024, 
            temperature=0.3,
        )
        recommendation = response.choices[0].message.content
        return {"recommendation": recommendation}
    except Exception as e:
        return {"recommendation": f"Could not generate recommendation: {str(e)}"}