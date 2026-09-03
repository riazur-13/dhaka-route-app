"use client";

import { useEffect, useRef, useState } from "react";
import {
  MapContainer,
  TileLayer,
  Marker,
  Polyline,
  useMapEvents,
  Popup,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import {
  fetchRoute,
  submitFare,
  getAverageFare,
  reverseGeocode,
  getAIRecommendation,
  pingHealth,
  type FareSubmitResult,
} from "../lib/osrm";
import SearchBox from "./SearchBox";
import { RICKSHAW_STANDS } from "../lib/rickshawStands";

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
const standIcon = L.divIcon({
  className: "",
  html: `<div style="
    width: 24px;
    height: 24px;
    background: #f59e0b;
    border: 2px solid white;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.4);
    cursor: pointer;
  ">🛺</div>`,
  iconSize: [24, 24],
  iconAnchor: [12, 12],
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

function formatWalkingTime(distanceKm?: number) {
  if (!distanceKm) return "N/A";

  const WALKING_SPEED_KMH = 4.5; // Realistic walking speed
  const hours = distanceKm / WALKING_SPEED_KMH;
  const minutes = Math.round(hours * 60);

  return minutes < 60
    ? `${minutes} min`
    : `${Math.floor(minutes / 60)} hr${minutes % 60 ? ` ${minutes % 60} min` : ""}`;
}

interface RouteData {
  coordinates: [number, number][];
  distance: number;
  duration: number;
}

/** Which of the two search boxes a place name belongs to. */
type NameField = "start" | "end";

export default function Map() {
  const [start, setStart] = useState<[number, number] | null>(null);
  const [end, setEnd] = useState<[number, number] | null>(null);
  const [routeData, setRouteData] = useState<RouteData | null>(null);
  const [loading, setLoading] = useState(false);

  const [startName, setStartName] = useState("");
  const [endName, setEndName] = useState("");

  const [fareInput, setFareInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [fareStatus, setFareStatus] = useState<FareSubmitResult | null>(null);
  const [avgFare, setAvgFare] = useState<number | null>(null);
  const [submissionCount, setSubmissionCount] = useState(0);

  const [aiRecommendation, setAiRecommendation] = useState<string | null>(null);

  // Errors from event handlers and async work never reach a React error
  // boundary — they run after render — so they have to be caught and put into
  // state by hand. Kept separate from fareStatus, which belongs to the
  // submission form and has its own lifecycle.
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // True while a place name is being looked up for that box. Drives the
  // skeleton in SearchBox and nothing else.
  const [startNamePending, setStartNamePending] = useState(false);
  const [endNamePending, setEndNamePending] = useState(false);

  // One in-flight reverse geocode per box. Deliberately per-field rather than a
  // single shared controller: the common rapid pair of clicks is start-then-end,
  // and a shared controller would cancel the start lookup because the user
  // picked a destination — throwing away a good name for no benefit and
  // stranding that box's skeleton with nothing left to resolve it. Keyed this
  // way, a lookup is only ever cancelled by a newer lookup for the same box,
  // which is the case the staleness actually arises in.
  const geocodeAbort = useRef<Record<NameField, AbortController | null>>({
    start: null,
    end: null,
  });

  // Wake the backend before the user clicks anything. Render's free tier stops
  // the container when idle, and the first request pays the whole cold start —
  // which, before this, was a map click that showed nothing at all until it
  // finished. Fire and forget: no await on render, no state, and nothing shown
  // if it fails, because the user has not asked for anything yet.
  useEffect(() => {
    void pingHealth();
  }, []);

  /**
   * Look up a place name, cancelling any previous lookup for the same box.
   *
   * Returns null when this lookup was the one cancelled, in which case a newer
   * lookup already owns the name and the pending flag and the caller must not
   * touch either.
   */
  async function resolvePlaceName(field: NameField, lat: number, lng: number) {
    geocodeAbort.current[field]?.abort();

    const controller = new AbortController();
    geocodeAbort.current[field] = controller;

    const result = await reverseGeocode(lat, lng, controller.signal);

    // Only clear the slot if it is still ours; a newer lookup may have claimed
    // it while this one was in flight.
    if (geocodeAbort.current[field] === controller) {
      geocodeAbort.current[field] = null;
    }

    return result;
  }

  function applyPlaceName(field: NameField, name: string) {
    if (field === "start") {
      setStartName(name);
      setStartNamePending(false);
    } else {
      setEndName(name);
      setEndNamePending(false);
    }
  }

  function handleCurrentLocation() {
    if (!navigator.geolocation) {
      alert("Geolocation is not supported by your browser");
      return;
    }

    setErrorMessage(null);

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const lat = position.coords.latitude;
        const lng = position.coords.longitude;

        // Marker and skeleton first, before the await, same as a map click.
        setStart([lat, lng]);
        setStartName("");
        setStartNamePending(true);
        setRouteData(null);
        setAvgFare(null);
        setAiRecommendation(null);

        const result = await resolvePlaceName("start", lat, lng);

        // Cancelled — a newer lookup owns this box now. Nothing to do, and in
        // particular nothing to say: the user did this, it is not a failure.
        if (result === null) return;

        setErrorMessage(result.message ?? null);
        applyPlaceName("start", result.name);

        if (end) await getRoute([lat, lng], end, endName);
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

  // destinationName is passed in rather than read from endName state — callers
  // often set the name and route in the same handler, so the state value would
  // still be the previous render's.
  async function getRoute(
    startPoint: [number, number],
    endPoint: [number, number],
    destinationName: string,
  ) {
    setLoading(true);
    setFareStatus(null);

    // try/finally so a throw anywhere below cannot leave "Finding route..."
    // stuck on screen forever. The pill is the only sign the app is busy.
    try {
      const result = await fetchRoute(startPoint, endPoint);

      if (!result.ok || !result.route) {
        setErrorMessage(result.message ?? "Could not find a route between those two points.");
        return;
      }

      const route = result.route;
      setRouteData(route);

      // The route is already on the map by this point and stays there. A fare
      // we could not look up, or advice we could not fetch, is a missing
      // extra — not a reason to throw away a route that worked.
      //
      // The functional form keeps the *first* failure: `errorMessage` closed
      // over here is the previous render's value, and a reverse-geocode
      // failure earlier in the same click may already have set one.
      const reportFirstFailure = (message: string) =>
        setErrorMessage((previous) => previous ?? message);

      const avg = await getAverageFare(toKm(route.distance), "rickshaw");
      if (avg.ok) {
        // averageFare null here means nobody has submitted for this distance,
        // which is a real answer and renders as such.
        setAvgFare(avg.averageFare);
        setSubmissionCount(avg.submissionCount);
      } else {
        reportFirstFailure(avg.message ?? "Could not load the crowdsourced fare for this trip.");
      }

      const ai = await getAIRecommendation(
        toKm(route.distance),
        "rickshaw",
        destinationName || "Dhaka",
      );
      if (ai.ok) {
        setAiRecommendation(ai.recommendation);
      } else {
        reportFirstFailure(ai.message ?? "Could not load the fare advice for this trip.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleMapClick(lat: number, lng: number) {
    setErrorMessage(null);

    const point: [number, number] = [lat, lng];

    // Everything the click already implies happens now, before any await. The
    // marker's position is known the instant the user clicks — only its label
    // needs the network — and waiting on a reverse geocode to draw it meant a
    // cold Render container could leave the first click looking ignored for the
    // best part of a minute. The name arrives later and fills the skeleton in.
    const field: NameField = !start || end ? "start" : "end";
    const routeFrom = field === "end" ? start : null;

    if (field === "start") {
      setStart(point);
      setStartName("");
      setStartNamePending(true);
    } else {
      setEnd(point);
      setEndName("");
      setEndNamePending(true);
    }

    // The third click starts over: the old route and its fare no longer
    // describe anything on screen.
    if (start && end) {
      setEnd(null);
      setEndName("");
      setEndNamePending(false);
      setRouteData(null);
      setAvgFare(null);
      setFareInput("");
      setFareStatus(null);
      setAiRecommendation(null);
    }

    const result = await resolvePlaceName(field, lat, lng);

    // Cancelled by a newer click on the same box. That newer lookup owns the
    // name, the skeleton and the marker now, so this one touches nothing and
    // says nothing — a second click is not an error and must raise no banner.
    if (result === null) return;

    setErrorMessage(result.message ?? null);
    applyPlaceName(field, result.name);

    if (routeFrom) await getRoute(routeFrom, point, result.name);
  }

  async function handleSearchSelect(
    type: "start" | "end",
    lat: number,
    lng: number,
    name: string,
  ) {
    const point: [number, number] = [lat, lng];

    setErrorMessage(null);

    // Search already knows the name, so any reverse geocode still running for
    // this box is both redundant and a stale write waiting to happen. Cancel it
    // and drop the skeleton — otherwise it would sit on top of a name that is
    // already correct, with nothing left in flight to ever clear it.
    geocodeAbort.current[type]?.abort();
    geocodeAbort.current[type] = null;
    if (type === "start") setStartNamePending(false);
    else setEndNamePending(false);

    if (type === "start") {
      setStart(point);
      setStartName(name);
      setRouteData(null);
      setAvgFare(null);
      setAiRecommendation(null);
      if (end) await getRoute(point, end, endName);
    } else {
      setEnd(point);
      setEndName(name);
      setRouteData(null);
      setAvgFare(null);
      setAiRecommendation(null);
      if (start) await getRoute(start, point, name);
    }
  }

  async function handleFareSubmit() {
    if (!routeData || !fareInput) return;
    setSubmitting(true);
    setFareStatus(null);

    const result = await submitFare(
      toKm(routeData.distance),
      parseFloat(fareInput),
      "rickshaw",
    );
    setFareStatus(result);

    // On rejection the input is left intact so the user can correct the amount.
    if (result.ok) {
      // Only a successful refresh replaces what is on screen. If the re-read
      // fails, the previous average stays — the submission itself succeeded,
      // and blanking the figure would make it look as though it had not.
      const avg = await getAverageFare(toKm(routeData.distance), "rickshaw");
      if (avg.ok) {
        setAvgFare(avg.averageFare);
        setSubmissionCount(avg.submissionCount);
      }
      setFareInput("");
    }

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
          pending={startNamePending}
          onSelect={(lat, lng, name) =>
            handleSearchSelect("start", lat, lng, name)
          }
        />
        <div style={{ height: "1px", background: "#334155" }} />
        <SearchBox
          placeholder="To — search or click map"
          color="amber"
          value={endName}
          pending={endNamePending}
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
              {formatWalkingTime(toKm(routeData.distance))}
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

            {/* Submission result — surfaces backend range / AI validation rejections */}
            {fareStatus && (
              <div
                style={{
                  marginTop: "8px",
                  padding: "8px 10px",
                  borderRadius: "6px",
                  background: fareStatus.ok ? "#052e16" : "#450a0a",
                  border: `1px solid ${fareStatus.ok ? "#22c55e" : "#dc2626"}`,
                }}
              >
                <p
                  style={{
                    color: fareStatus.ok ? "#86efac" : "#fca5a5",
                    fontSize: "12px",
                    lineHeight: "1.5",
                  }}
                >
                  {fareStatus.ok ? "✅" : "⚠️"} {fareStatus.message}
                </p>
              </div>
            )}
          </div>

          {/* AI Recommendation — inside info panel */}
          {aiRecommendation && (
            <>
              <div
                style={{
                  height: "1px",
                  background: "#334155",
                  margin: "8px 0",
                }}
              />
              <div
                style={{
                  padding: "12px",
                  background: "#0f172a",
                  borderRadius: "8px",
                  border: "1px solid #6366f1",
                  height: "auto", // Let it expand naturally based on content
                  minHeight: "fit-content", // Ensure it respects the content layout
                  display: "flex",
                  flexDirection: "column",
                  gap: "6px",
                }}
              >
                <p
                  style={{
                    color: "#818cf8",
                    fontWeight: 700,
                    fontSize: "12px",
                    marginBottom: "2px",
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
                    lineHeight: "1.6",
                    fontFamily: '"Noto Sans Bengali", sans-serif',
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    margin: 0,
                  }}
                >
                  {aiRecommendation}
                </p>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Error banner ── */}
      {errorMessage && (
        <div
          role="alert"
          style={{
            position: "absolute",
            top: "16px",
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 1000,
            background: "rgba(127,29,29,0.95)",
            border: "1px solid #ef4444",
            color: "white",
            padding: "8px 16px",
            borderRadius: "8px",
            fontSize: "13px",
            display: "flex",
            alignItems: "center",
            gap: "12px",
            maxWidth: "90vw",
          }}
        >
          <span>{errorMessage}</span>
          <button
            type="button"
            onClick={() => setErrorMessage(null)}
            aria-label="Dismiss"
            style={{
              background: "transparent",
              border: "none",
              color: "white",
              cursor: "pointer",
              fontSize: "16px",
              lineHeight: 1,
              padding: 0,
              flexShrink: 0,
            }}
          >
            ×
          </button>
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
        {/* Rickshaw stand markers */}
        {RICKSHAW_STANDS.map((stand) => (
          <Marker
            key={stand.id}
            position={[stand.lat, stand.lng]}
            icon={standIcon}
          >
            <Popup>
              <div style={{ minWidth: "140px" }}>
                <p
                  style={{
                    fontWeight: 700,
                    fontSize: "14px",
                    marginBottom: "4px",
                    color: "#f59e0b",
                  }}
                >
                  🛺 {stand.namebn}
                </p>
                <p
                  style={{
                    fontSize: "12px",
                    color: "#94a3b8",
                    marginBottom: "4px",
                  }}
                >
                  {stand.name} — {stand.area}
                </p>
                <p
                  style={{
                    fontSize: "12px",
                    color: "black",
                  }}
                >
                  ⏱️ Wait: {stand.waitTime}
                </p>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}
