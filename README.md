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

**Backend:** Python, FastAPI, SQLite, Render

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

## Known Limitations

- SQLite resets on Render redeploy (free tier), so submitted fares do not survive a deploy
- OSRM public server has rate limits
- Rickshaw paths are approximated by the walking profile; OSRM has no rickshaw profile
- Rickshaw stand locations are a hand-maintained list, not a live data source
