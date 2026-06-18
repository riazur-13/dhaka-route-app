'use client';

import { useState } from 'react';
import { MapContainer, TileLayer, Marker, Polyline, useMapEvents } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { fetchRoute } from '../lib/osrm';

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

// Helper functions
function toKm(metres: number) {
  return (metres / 1000).toFixed(1);
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

  async function handleMapClick(lat: number, lng: number) {
    if (!start) {
      setStart([lat, lng]);
    } else if (!end) {
      setEnd([lat, lng]);
      setLoading(true);

      const data = await fetchRoute(start, [lat, lng]);
      if (data) setRouteData(data);

      setLoading(false);
    } else {
      setStart([lat, lng]);
      setEnd(null);
      setRouteData(null);
    }
  }

  return (
    <div style={{ position: 'relative', width: '100%', height: '100vh' }}>

      {/* Info panel — top right */}
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
          minWidth: '180px',
          border: '1px solid #334155',
        }}>
          {/* Walking */}
          <div>
            <p style={{ color: '#22c55e', fontWeight: 700, fontSize: '13px', marginBottom: '4px' }}>
              🚶 Walking
            </p>
            <p style={{ color: 'white', fontSize: '15px', fontWeight: 600 }}>
              {toKm(routeData.distance)} km
            </p>
            <p style={{ color: '#94a3b8', fontSize: '12px' }}>
              {toMinutes(routeData.duration)} min
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
            <p style={{ color: '#94a3b8', fontSize: '12px' }}>
              {toMinutes(routeData.duration * 1.3)} min
            </p>
            <p style={{ color: '#f59e0b', fontSize: '12px', marginTop: '4px' }}>
              ৳{Math.round(30 + (routeData.distance / 1000) * 25)} est. fare
            </p>
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

      {/* Legend — bottom left */}
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

      {/* Hint */}
      {!start && (
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
          whiteSpace: 'nowrap',
        }}>
          📍 Click to set start point
        </div>
      )}

      {start && !end && (
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
          whiteSpace: 'nowrap',
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