from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from database import init_db, get_connection

app = FastAPI()

# Allow Next.js frontend to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://dhaka-route-app.vercel.app"],
    allow_credentials=True,
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