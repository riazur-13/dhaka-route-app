from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from database import init_db, get_connection

app = FastAPI()

# Allow Next.js frontend to talk to this API
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
        "distance":    route["distance"],   # metres
        "duration":    route["duration"],   # seconds
    }

class FareSubmission(BaseModel):
    distance_km: float
    fare_amount: float
    route_type: str  # "walking" or "rickshaw"


# ── NEW: Submit a fare ──
@app.post("/fares")
def submit_fare(submission: FareSubmission):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO fare_submissions (distance_km, fare_amount, route_type) VALUES (?, ?, ?)",
        (submission.distance_km, submission.fare_amount, submission.route_type),
    )
    conn.commit()
    conn.close()
    return {"message": "Fare submitted successfully"}


# ── NEW: Get average fare for a distance range ──
@app.get("/fares/average")
def get_average_fare(distance_km: float, route_type: str):
    # Group trips within ±0.5km of the given distance
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