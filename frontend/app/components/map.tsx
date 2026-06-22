"use client";

import { useState } from "react";
import {
  MapContainer,
  TileLayer,
  Marker,
  Polyline,
  useMapEvents,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import {
  fetchRoute,
  submitFare,
  getAverageFare,
  reverseGeocode,
  getAIRecommendation,
} from "../lib/osrm";
import SearchBox from "./SearchBox";

const startIcon = L.divIcon({
  className: "",
  html: '<div style="width:16px;height:16px;background:#22c55e;border:3px solid white;border-radius:50%;box-shadow:0 2px 6px rgba(0,0,0,0.4)"></div>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

const endIcon = L.divIcon({
  className: "",
  html: '<div style="width:16px;height:16px;background:#ef4444;border:3px solid white;border-radius:50%;box-shadow:0 2px 6px rgba(0,0,0,0.4)"></div>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

function ClickHandler({
  onMapClick,
}: {
  onMapClick: (lat: number, lng: number) => void;
}) {
  useMapEvents({
    click(e) {
      onMapClick(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

function toKm(metres: number) {
  return parseFloat((metres / 1000).toFixed(1));
}

function formatWalkingTime(seconds: number, distanceKm: number) {
  // Walking speed average = 5km/h = 83m/min
  const realisticMins = Math.round((distanceKm / 5) * 60);
  return `${realisticMins} min`;
}

interface RouteData {
  coordinates: [number, number][];
  distance: number;
  duration: number;
}

export default function Map() {
  const [start, setStart] = useState<[number, number] | null>(null);
  const [end, setEnd] = useState<[number, number] | null>(null);
  const [routeData, setRouteData] = useState<RouteData | null>(null);
  const [loading, setLoading] = useState(false);

  const [startName, setStartName] = useState("");
  const [endName, setEndName] = useState("");

  const [fareInput, setFareInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [avgFare, setAvgFare] = useState<number | null>(null);
  const [submissionCount, setSubmissionCount] = useState(0);

  const [aiRecommendation, setAiRecommendation] = useState<string | null>(null);

  function handleCurrentLocation() {
    if (!navigator.geolocation) {
      alert("Geolocation is not supported by your browser");
      return;
    }

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const lat = position.coords.latitude;
        const lng = position.coords.longitude;
        const name = await reverseGeocode(lat, lng);
        setStart([lat, lng]);
        setStartName(name);
        setRouteData(null);
        setAvgFare(null);
        setAiRecommendation(null);
        if (end) await getRoute([lat, lng], end);
      },
      (error) => {
        const messages: Record<number, string> = {
          1: "Permission denied — please allow location access in your browser settings",
          2: "Location unavailable — could not detect your position",
          3: "Request timed out — please try again",
        };
        alert(messages[error.code] || "Could not get your location");
        console.error("Geolocation error code:", error.code, error.message);
      },
    );
  }

  async function getRoute(
    startPoint: [number, number],
    endPoint: [number, number],
  ) {
    setLoading(true);
    const data = await fetchRoute(startPoint, endPoint);
    if (data) {
      setRouteData(data);
      const avg = await getAverageFare(toKm(data.distance), "rickshaw");
      setAvgFare(avg.average_fare);
      setSubmissionCount(avg.submission_count);
      const ai = await getAIRecommendation(
        toKm(data.distance),
        "rickshaw",
        endName || "Dhaka",
      );
      setAiRecommendation(ai);
    }
    setLoading(false);
  }

  async function handleMapClick(lat: number, lng: number) {
    const name = await reverseGeocode(lat, lng);

    if (!start) {
      setStart([lat, lng]);
      setStartName(name);
    } else if (!end) {
      const endPoint: [number, number] = [lat, lng];
      setEnd(endPoint);
      setEndName(name);
      await getRoute(start, endPoint);
    } else {
      setStart([lat, lng]);
      setEnd(null);
      setStartName(name);
      setEndName("");
      setRouteData(null);
      setAvgFare(null);
      setFareInput("");
      setAiRecommendation(null);
    }
  }

  async function handleSearchSelect(
    type: "start" | "end",
    lat: number,
    lng: number,
    name: string,
  ) {
    const point: [number, number] = [lat, lng];

    if (type === "start") {
      setStart(point);
      setStartName(name);
      setRouteData(null);
      setAvgFare(null);
      setAiRecommendation(null);
      if (end) await getRoute(point, end);
    } else {
      setEnd(point);
      setEndName(name);
      setRouteData(null);
      setAvgFare(null);
      setAiRecommendation(null);
      if (start) await getRoute(start, point);
    }
  }

  async function handleFareSubmit() {
    if (!routeData || !fareInput) return;
    setSubmitting(true);
    await submitFare(
      toKm(routeData.distance),
      parseFloat(fareInput),
      "rickshaw",
    );
    const avg = await getAverageFare(toKm(routeData.distance), "rickshaw");
    setAvgFare(avg.average_fare);
    setSubmissionCount(avg.submission_count);
    setFareInput("");
    setSubmitting(false);
  }

  return (
    <div style={{ position: "relative", width: "100%", height: "100vh" }}>
      {/* ── Search Panel ── */}
      <div
        style={{
          position: "absolute",
          top: "16px",
          left: "50%",
          transform: "translateX(-50%)",
          zIndex: 1000,
          background: "rgba(15,23,42,0.95)",
          padding: "12px 16px",
          borderRadius: "12px",
          backdropFilter: "blur(8px)",
          border: "1px solid #334155",
          display: "flex",
          flexDirection: "column",
          gap: "8px",
          width: "320px",
        }}
      >
        <SearchBox
          placeholder="From — search or click map"
          color="green"
          value={startName}
          onSelect={(lat, lng, name) =>
            handleSearchSelect("start", lat, lng, name)
          }
        />
        <div style={{ height: "1px", background: "#334155" }} />
        <SearchBox
          placeholder="To — search or click map"
          color="amber"
          value={endName}
          onSelect={(lat, lng, name) =>
            handleSearchSelect("end", lat, lng, name)
          }
        />

        {/* Current location button */}
        <button
          onClick={handleCurrentLocation}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "6px",
            width: "100%",
            padding: "8px",
            borderRadius: "8px",
            border: "1px solid #334155",
            background: "#1e293b",
            color: "#94a3b8",
            fontSize: "12px",
            cursor: "pointer",
            transition: "all 0.2s",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "#334155";
            e.currentTarget.style.color = "white";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "#1e293b";
            e.currentTarget.style.color = "#94a3b8";
          }}
        >
          📍 Use my current location as start
        </button>
      </div>

      {/* ── Info + Fare Panel ── */}
      {routeData && (
        <div
          style={{
            position: "absolute",
            top: "16px",
            right: "16px",
            zIndex: 1000,
            background: "rgba(15,23,42,0.95)",
            padding: "16px",
            borderRadius: "12px",
            backdropFilter: "blur(8px)",
            display: "flex",
            flexDirection: "column",
            gap: "12px",
            minWidth: "220px",
            maxWidth: "260px",
            maxHeight: "85vh",
            overflowY: "auto",
            border: "1px solid #334155",
          }}
        >
          {/* Walking */}
          <div>
            <p
              style={{
                color: "#22c55e",
                fontWeight: 700,
                fontSize: "13px",
                marginBottom: "4px",
              }}
            >
              🚶 Walking
            </p>
            <p style={{ color: "white", fontSize: "15px", fontWeight: 600 }}>
              {toKm(routeData.distance)} km ·{" "}
              {formatWalkingTime(routeData.duration, toKm(routeData.distance))}{" "}
              min
            </p>
          </div>

          <div style={{ height: "1px", background: "#334155" }} />

          {/* Rickshaw */}
          <div>
            <p
              style={{
                color: "#f59e0b",
                fontWeight: 700,
                fontSize: "13px",
                marginBottom: "4px",
              }}
            >
              🛺 Rickshaw
            </p>
            <p style={{ color: "white", fontSize: "15px", fontWeight: 600 }}>
              {toKm(routeData.distance)} km
            </p>

            {avgFare ? (
              <p
                style={{
                  color: "#f59e0b",
                  fontSize: "14px",
                  marginTop: "6px",
                  fontWeight: 600,
                }}
              >
                ৳{avgFare} avg{" "}
                <span
                  style={{
                    color: "#94a3b8",
                    fontWeight: 400,
                    fontSize: "12px",
                  }}
                >
                  ({submissionCount} trip{submissionCount !== 1 ? "s" : ""})
                </span>
              </p>
            ) : (
              <p
                style={{ color: "#94a3b8", fontSize: "12px", marginTop: "6px" }}
              >
                No fare data yet for this distance
              </p>
            )}
            {/* Rickshaw distance warning */}
            {toKm(routeData.distance) > 15 && (
              <div
                style={{
                  marginTop: "6px",
                  padding: "8px 10px",
                  background: "#450a0a",
                  borderRadius: "6px",
                  border: "1px solid #dc2626",
                }}
              >
                <p style={{ color: "#fca5a5", fontSize: "12px" }}>
                  ⚠️ {toKm(routeData.distance)} km is too far for a rickshaw.
                  Consider taking a CNG or bus instead.
                </p>
              </div>
            )}

            {/* Fare input */}
            <div style={{ display: "flex", gap: "6px", marginTop: "10px" }}>
              <input
                type="number"
                placeholder="Your fare (৳)"
                value={fareInput}
                onChange={(e) => setFareInput(e.target.value)}
                style={{
                  flex: 1,
                  padding: "6px 8px",
                  borderRadius: "6px",
                  border: "1px solid #334155",
                  background: "#0f172a",
                  color: "white",
                  fontSize: "13px",
                  width: "100px",
                }}
              />
              <button
                onClick={handleFareSubmit}
                disabled={submitting || !fareInput}
                style={{
                  padding: "6px 12px",
                  borderRadius: "6px",
                  border: "none",
                  background: submitting ? "#475569" : "#f59e0b",
                  color: "white",
                  fontSize: "13px",
                  fontWeight: 600,
                  cursor: submitting ? "not-allowed" : "pointer",
                }}
              >
                {submitting ? "..." : "Submit"}
              </button>
            </div>
          </div>

          {/* AI Recommendation — inside info panel */}
          {aiRecommendation && (
            <>
              <div style={{ height: "1px", background: "#334155" }} />
              <div
                style={{
                  padding: "12px",
                  background: "#0f172a",
                  borderRadius: "8px",
                  border: "1px solid #6366f1",
                }}
              >
                <p
                  style={{
                    color: "#818cf8",
                    fontWeight: 700,
                    fontSize: "12px",
                    marginBottom: "6px",
                    display: "flex",
                    alignItems: "center",
                    gap: "4px",
                  }}
                >
                  🤖 AI পরামর্শ
                </p>
                <p
                  style={{
                    color: "#e2e8f0",
                    fontSize: "13px",
                    lineHeight: "1.8",
                    fontFamily: '"Noto Sans Bengali", sans-serif',
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {aiRecommendation}
                </p>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Loading ── */}
      {loading && (
        <div
          style={{
            position: "absolute",
            bottom: "40px",
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 1000,
            background: "rgba(15,23,42,0.9)",
            color: "white",
            padding: "8px 16px",
            borderRadius: "8px",
            fontSize: "13px",
          }}
        >
          Finding route...
        </div>
      )}

      {/* ── Legend ── */}
      <div
        style={{
          position: "absolute",
          bottom: "32px",
          left: "16px",
          zIndex: 1000,
          background: "rgba(15,23,42,0.9)",
          padding: "12px 16px",
          borderRadius: "12px",
          backdropFilter: "blur(8px)",
          display: "flex",
          flexDirection: "column",
          gap: "8px",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            color: "white",
            fontSize: "13px",
          }}
        >
          <div
            style={{
              width: "24px",
              height: "4px",
              background: "#22c55e",
              borderRadius: "2px",
            }}
          />
          🚶 Walking
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            color: "white",
            fontSize: "13px",
          }}
        >
          <div
            style={{
              width: "24px",
              height: "4px",
              background: "#f59e0b",
              borderRadius: "2px",
            }}
          />
          🛺 Rickshaw
        </div>
      </div>

      <MapContainer
        center={[23.8103, 90.4125]}
        zoom={13}
        style={{ width: "100%", height: "100vh" }}
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="© OpenStreetMap contributors"
        />

        <ClickHandler onMapClick={handleMapClick} />

        {start && <Marker position={start} icon={startIcon} />}
        {end && <Marker position={end} icon={endIcon} />}

        {routeData && (
          <Polyline
            positions={routeData.coordinates}
            color="#22c55e"
            weight={6}
          />
        )}
        {routeData && (
          <Polyline
            positions={routeData.coordinates}
            color="#f59e0b"
            weight={3}
            dashArray="10, 10"
          />
        )}
      </MapContainer>
    </div>
  );
}
