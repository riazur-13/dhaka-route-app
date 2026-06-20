# 🗺️ Dhaka Route Finder

A map app for Dhaka, Bangladesh showing walking and rickshaw routes with crowdsourced fare data.

🌐 **Live:** [dhaka-route-app.vercel.app](https://dhaka-route-app.vercel.app)

---

## Features

- Click or search to set start and end points
- Walking 🚶 and rickshaw 🛺 routes displayed simultaneously
- Click on map → place name appears in search box automatically
- 📍 Current location button
- 💰 Submit real fares → see crowdsourced average fare

---

## Tech Stack

**Frontend:** Next.js 14, TypeScript, Leaflet, OpenStreetMap, Vercel

**Backend:** Python, FastAPI, SQLite, Render

**APIs:** OSRM (routing), Nominatim (place search + reverse geocoding)

---

## Run Locally

**Frontend**
```bash
cd frontend
npm install && npm run dev
```

**Backend**
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

---

## Known Limitations

- SQLite resets on Render redeploy (free tier)
- OSRM public server has rate limits
