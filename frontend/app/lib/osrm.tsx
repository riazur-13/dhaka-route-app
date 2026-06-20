const API_BASE = 'https://dhaka-route-app-4.onrender.com'; // ✅ no space

export async function fetchRoute(
  start: [number, number],
  end: [number, number]
) {
  const url = `${API_BASE}/route?start_lat=${start[0]}&start_lng=${start[1]}&end_lat=${end[0]}&end_lng=${end[1]}`;

  const res = await fetch(url);
  const data = await res.json();

  if (!data.coordinates) return null;

  const coordinates = data.coordinates.map(([lng, lat]: [number, number]) => [lat, lng] as [number, number]);

  return {
    coordinates,
    distance: data.distance,
    duration: data.duration,
  };
}

export async function submitFare(
  distanceKm: number,
  fareAmount: number,
  routeType: 'walking' | 'rickshaw'
) {
  const res = await fetch(`${API_BASE}/fares`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      distance_km: distanceKm,
      fare_amount: fareAmount,
      route_type: routeType,
    }),
  });
  return res.json();
}

export async function getAverageFare(
  distanceKm: number,
  routeType: 'walking' | 'rickshaw'
) {
  const url = `${API_BASE}/fares/average?distance_km=${distanceKm}&route_type=${routeType}`; // ✅ uses API_BASE
  const res = await fetch(url);
  return res.json();
}
export async function searchPlace(query: string) {
  const url = `${API_BASE}/search?query=${encodeURIComponent(query)}`;
  const res = await fetch(url);
  const data = await res.json();
  return data.results as {
    name: string;
    full_name: string;
    lat: number;
    lng: number;
  }[];
}
export async function reverseGeocode(lat: number, lng: number): Promise<string> {
  const url = `${API_BASE}/reverse-geocode?lat=${lat}&lng=${lng}`;
  const res = await fetch(url);
  const data = await res.json();
  return data.name || `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
}