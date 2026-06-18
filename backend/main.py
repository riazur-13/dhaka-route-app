from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI()

# Allow Next.js frontend to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000","*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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