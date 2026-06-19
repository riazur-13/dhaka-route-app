'use client';

import { useState } from 'react';
import { MapContainer, TileLayer, Marker, Polyline, useMapEvents } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { fetchRoute, submitFare, getAverageFare } from '../lib/osrm';

const startIcon = L.divIcon({
  className: '',
  html: '<div style="width:16px;height:16px;background:#22c55e;border:3px solid white;border-radius:50%;box-shadow:0 2px 6px rgba(0,0,0,0.4)"></div>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

const endIcon = L.divIcon({
  className: '',
  html: '<div style="width:16px;height:16px;background:#ef4444;border:3px solid white;border-radius:50%;box-shadow:0 2px 6px rgba(0,0,0,0.4)"></div>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

function ClickHandler({ onMapClick }: { onMapClick: (lat: number, lng: number) => void }) {
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

function toMinutes(seconds: number) {
  return Math.round(seconds / 60);
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

  // Fare submission state
  const [fareInput, setFareInput] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [avgFare, setAvgFare] = useState<number | null>(null);
  const [submissionCount, setSubmissionCount] = useState(0);

  async function handleMapClick(lat: number, lng: number) {
    if (!start) {
      setStart([lat, lng]);
    } else if (!end) {
      setEnd([lat, lng]);
      setLoading(true);

      const data = await fetchRoute(start, [lat, lng]);
      if (data) {
        setRouteData(data);
        // Fetch existing average fare for this distance
        const avg = await getAverageFare(toKm(data.distance), 'rickshaw');
        setAvgFare(avg.average_fare);
        setSubmissionCount(avg.submission_count);
      }

      setLoading(false);
    } else {
      setStart([lat, lng]);
      setEnd(null);
      setRouteData(null);
      setAvgFare(null);
      setFareInput('');
    }
  }

  async function handleFareSubmit() {
    if (!routeData || !fareInput) return;

    setSubmitting(true);

    await submitFare(toKm(routeData.distance), parseFloat(fareInput), 'rickshaw');

    // Refresh the average after submitting
    const avg = await getAverageFare(toKm(routeData.distance), 'rickshaw');
    setAvgFare(avg.average_fare);
    setSubmissionCount(avg.submission_count);

    setFareInput('');
    setSubmitting(false);
  }

  return (
    <div style={{ position: 'relative', width: '100%', height: '100vh' }}>

      {/* Info + fare panel — top right */}
      {routeData && (
        <div style={{
          position: 'absolute',
          top: '16px',
          right: '16px',
          zIndex: 1000,
          background: 'rgba(15,23,42,0.95)',
          padding: '16px',
          borderRadius: '12px',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
          minWidth: '220px',
          border: '1px solid #334155',
        }}>
          {/* Walking */}
          <div>
            <p style={{ color: '#22c55e', fontWeight: 700, fontSize: '13px', marginBottom: '4px' }}>
              🚶 Walking
            </p>
            <p style={{ color: 'white', fontSize: '15px', fontWeight: 600 }}>
              {toKm(routeData.distance)} km · {toMinutes(routeData.duration)} min
            </p>
          </div>

          <div style={{ height: '1px', background: '#334155' }} />

          {/* Rickshaw */}
          <div>
            <p style={{ color: '#f59e0b', fontWeight: 700, fontSize: '13px', marginBottom: '4px' }}>
              🛺 Rickshaw
            </p>
            <p style={{ color: 'white', fontSize: '15px', fontWeight: 600 }}>
              {toKm(routeData.distance)} km
            </p>

            {/* Crowdsourced average fare */}
            {avgFare ? (
              <p style={{ color: '#f59e0b', fontSize: '14px', marginTop: '6px', fontWeight: 600 }}>
                ৳{avgFare} avg <span style={{ color: '#94a3b8', fontWeight: 400, fontSize: '12px' }}>
                  ({submissionCount} trip{submissionCount !== 1 ? 's' : ''})
                </span>
              </p>
            ) : (
              <p style={{ color: '#94a3b8', fontSize: '12px', marginTop: '6px' }}>
                No fare data yet for this distance
              </p>
            )}

            {/* Fare submission input */}
            <div style={{ display: 'flex', gap: '6px', marginTop: '10px' }}>
              <input
                type="number"
                placeholder="Your fare (৳)"
                value={fareInput}
                onChange={(e) => setFareInput(e.target.value)}
                style={{
                  flex: 1,
                  padding: '6px 8px',
                  borderRadius: '6px',
                  border: '1px solid #334155',
                  background: '#0f172a',
                  color: 'white',
                  fontSize: '13px',
                  width: '100px',
                }}
              />
              <button
                onClick={handleFareSubmit}
                disabled={submitting || !fareInput}
                style={{
                  padding: '6px 12px',
                  borderRadius: '6px',
                  border: 'none',
                  background: submitting ? '#475569' : '#f59e0b',
                  color: 'white',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: submitting ? 'not-allowed' : 'pointer',
                }}
              >
                {submitting ? '...' : 'Submit'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Loading indicator */}
      {loading && (
        <div style={{
          position: 'absolute',
          top: '16px',
          left: '50%',
          transform: 'translateX(-50%)',
          zIndex: 1000,
          background: 'rgba(15,23,42,0.9)',
          color: 'white',
          padding: '8px 16px',
          borderRadius: '8px',
          fontSize: '13px',
        }}>
          Finding route...
        </div>
      )}

      {/* Legend */}
      <div style={{
        position: 'absolute',
        bottom: '32px',
        left: '16px',
        zIndex: 1000,
        background: 'rgba(15,23,42,0.9)',
        padding: '12px 16px',
        borderRadius: '12px',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'white', fontSize: '13px' }}>
          <div style={{ width: '24px', height: '4px', background: '#22c55e', borderRadius: '2px' }} />
          🚶 Walking
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'white', fontSize: '13px' }}>
          <div style={{ width: '24px', height: '4px', background: '#f59e0b', borderRadius: '2px' }} />
          🛺 Rickshaw
        </div>
      </div>

      {/* Click hints */}
      {!start && (
        <div style={{
          position: 'absolute', top: '16px', left: '50%', transform: 'translateX(-50%)',
          zIndex: 1000, background: 'rgba(15,23,42,0.9)', color: 'white',
          padding: '8px 16px', borderRadius: '8px', fontSize: '13px', whiteSpace: 'nowrap',
        }}>
          📍 Click to set start point
        </div>
      )}

      {start && !end && (
        <div style={{
          position: 'absolute', top: '16px', left: '50%', transform: 'translateX(-50%)',
          zIndex: 1000, background: 'rgba(15,23,42,0.9)', color: 'white',
          padding: '8px 16px', borderRadius: '8px', fontSize: '13px', whiteSpace: 'nowrap',
        }}>
          🏁 Click to set destination
        </div>
      )}

      <MapContainer
        center={[23.8103, 90.4125]}
        zoom={13}
        style={{ width: '100%', height: '100vh' }}
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="© OpenStreetMap contributors"
        />

        <ClickHandler onMapClick={handleMapClick} />

        {start && <Marker position={start} icon={startIcon} />}
        {end && <Marker position={end} icon={endIcon} />}

        {routeData && (
          <Polyline positions={routeData.coordinates} color="#22c55e" weight={6} />
        )}
        {routeData && (
          <Polyline positions={routeData.coordinates} color="#f59e0b" weight={3} dashArray="10, 10" />
        )}
      </MapContainer>
    </div>
  );
}