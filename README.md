# 🗺️ Dhaka Route Finder

A map app for Dhaka, Bangladesh that routes a trip on foot and prices it as a rickshaw ride, using crowdsourced fare data.

🌐 **Live:** [dhaka-route-app.vercel.app](https://dhaka-route-app.vercel.app)

---

## Features

- Click or search to set start and end points
- One route, costed two ways: 🚶 walking time and 🛺 rickshaw fare shown side by side
- Nearby rickshaw stands marked on the map
- Click on map → place name appears in search box automatically
- 📍 Current location button
- 💰 Submit real fares → see crowdsourced average fare
- 🤖 AI checks submitted fares for plausibility and suggests a fair price

---

## Tech Stack

**Frontend:** Next.js 16, React 19, TypeScript, Tailwind, Leaflet, OpenStreetMap, Vercel

**Backend:** Python, FastAPI, Postgres (Neon), Render

**APIs:** OSRM (routing), Nominatim (place search + reverse geocoding), Groq (fare validation + recommendations)

---

## How routing works

There is **one** route request per trip, against OSRM's `foot` profile — Dhaka's rickshaws
use the same lanes and shortcuts pedestrians do, so the walking path is the better
approximation of a rickshaw's path than the driving one would be.

That single path is then presented two ways:

- **🚶 Walking** — distance and an estimated time at 4.5 km/h
- **🛺 Rickshaw** — the same distance, with the crowdsourced average fare for it, and a
  warning above 15 km suggesting a CNG or bus instead

The two lines drawn on the map are the same geometry in two styles, not two separate routes.

---

## Running the backend

The backend needs a Postgres database and a Groq key, both read from
`backend/.env`:

```
DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require
GROQ_API_KEY=...
GROQ_MODEL=openai/gpt-oss-20b   # optional; this is the default
USER_AGENT=DhakaRouteFinder/1.0 (github.com/riazur-13/dhaka-route-app)   # optional
```

Every one of these is read through `config.get_env`, which strips surrounding
whitespace — a trailing newline on a pasted `DATABASE_URL` has taken a deploy
down before. `GROQ_MODEL` exists so that a model being decommissioned is a
dashboard edit rather than a code change; both AI call sites read that one
value. `USER_AGENT` is sent on every request to Nominatim and OSRM, whose usage
policies ask to be able to identify and contact whoever is calling them — set it
to your own project if you fork this.

The `fare_submissions` and `geocode_cache` tables are created on start-up, so a
blank database is enough to boot against.

### Reverse geocoding is cached

Nominatim blocks shared datacenter IP ranges, and the free Render tier gives the
service one. Reverse-geocode results are therefore cached in Postgres, keyed on
latitude and longitude rounded to four decimal places — about 11 m, finer than
anyone can aim a click. Names are kept for 30 days. **Failures** are kept too,
for five minutes, so that repeatedly clicking a location we have just been
refused for does not send Nominatim a request each time.

When the cache cannot help and the upstream service will not answer, the
endpoints return **502** with a plain-string `detail`, and log the status code
and the first 200 characters of the response body. They no longer call `.json()`
on an unread response, which is how a Nominatim block page became a 500.

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

To run the tests, point `TEST_DATABASE_URL` at a **throwaway** database — the
fixtures empty the fare table between tests, so never give it the live one:

```bash
docker run --rm -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres --name fares-test postgres:17
pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres pytest
```

Without that variable the database tests skip locally, and fail in CI.

---

## Known Limitations

- OSRM public server has rate limits
- Rickshaw paths are approximated by the walking profile; OSRM has no rickshaw profile
- Rickshaw stand locations are a hand-maintained list, not a live data source
