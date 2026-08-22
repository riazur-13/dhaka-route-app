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

## How fares are calculated

**Python decides the fare. The AI only phrases it in Bengali.**

This used to work the other way round: the pricing rules lived as prose inside the
Groq prompt and the model invented the number. That made the same trip price
differently on two consecutive clicks, made the rules impossible to test, and meant
no fare at all whenever Groq was slow or down.

The rules now live in [`backend/fare_calculator.py`](backend/fare_calculator.py) as
pure functions, with every constant in [`backend/config.py`](backend/config.py):

1. **Base + per-km rate.** A flag fare charged at any distance, plus a per-kilometre
   rate that differs for pedal and battery rickshaws.
2. **A long-trip bend.** Beyond 8 km, only the *excess* distance is charged at the
   higher multiplier — so the curve bends rather than stepping, and a 7.9 km ride
   and an 8.1 km ride are priced within a couple of taka of each other.
3. **Crowdsourced data, if there is enough of it.** Under 5 submissions it is
   ignored; over 20 it dominates; in between the two are blended on a straight line,
   so no single submission ever flips the answer overnight.
4. **The floor, applied last.** See below.

`/ai-fare-recommendation` returns `fare_low`, `fare_high`, `source`
(`rules` / `blended` / `crowdsourced`), `sample_size` and `floor_applied` **whether
or not Groq answers**. When it does not, `recommendation_available` is `false` and
the Bengali text is a fallback string — the numbers are still there to render.

### The floor is policy, not arithmetic

The floor rates encode a **living wage for rickshaw pullers**, not a market price,
and crowdsourced data is never allowed to push a recommendation below them. A pile
of low submissions is evidence that haggling works, not evidence that a fare is
fair, so the crowd can move a number up through the floor and never down through it.

Because of that, the floor is clamped *after* every branch, and when it bites the
whole range is rebuilt around it — a 0.1 km ride is quoted 30–41, never 30–26 or a
zero-width 30–30 that would tell a passenger to refuse any counter-offer at all.

All of these numbers are **provisional** and meant to be tuned. They are plain
constants rather than environment variables on purpose: they are one coherent policy
rather than twelve independent settings, and changing pricing should cost a commit
and a review. `FARE_RATES_EFFECTIVE_DATE` records when they were last set.

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
blank database is enough to boot against. Schema changes to an existing table
arrive as idempotent `ALTER TABLE ... IF NOT EXISTS` statements in the same
`init_db()`, which is how `fare_submissions.submitted_by` is added. Nothing reads
that column yet — it records whether a passenger or a driver entered a fare, and
it is being captured now because it cannot be recovered later.

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
