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

export interface FareSubmitResult {
  ok: boolean;
  message: string;
}

export async function submitFare(
  distanceKm: number,
  fareAmount: number,
  routeType: 'walking' | 'rickshaw'
): Promise<FareSubmitResult> {
  let res: Response;

  try {
    res = await fetch(`${API_BASE}/fares`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        distance_km: distanceKm,
        fare_amount: fareAmount,
        route_type: routeType,
      }),
    });
  } catch {
    return { ok: false, message: 'Could not reach the server. Check your connection and try again.' };
  }

  const data = await res.json().catch(() => null);

  if (!res.ok) {
    // The backend rejects with a plain-string `detail` (range pre-filter or AI
    // validation). FastAPI's own 422 sends an array instead, which we don't show.
    const detail = typeof data?.detail === 'string' ? data.detail : null;
    return { ok: false, message: detail || 'Your fare was rejected. Please double-check the amount.' };
  }

  return { ok: true, message: data?.message || 'Thanks! Your fare was saved.' };
}

export async function getAverageFare(
  distanceKm: number,
  routeType: 'walking' | 'rickshaw'
) {
  const url = `${API_BASE}/fares/average?distance_km=${distanceKm}&route_type=${routeType}`; // ✅ uses API_BASE
  const res = await fetch(url);
  return res.json();
}
export interface PlaceResult {
  name: string;
  full_name: string;
  lat: number;
  lng: number;
}

export async function searchPlace(query: string): Promise<PlaceResult[]> {
  const url = `${API_BASE}/search?query=${encodeURIComponent(query)}`;
  let res: Response;

  try {
    res = await fetch(url);
  } catch {
    return [];
  }

  // Anything but a 200 has no `results` at all — the backend answers 502 with a
  // `detail` when Nominatim is blocked or down. This used to return undefined,
  // which the caller put straight into state and then read .length off.
  if (!res.ok) return [];

  const data = await res.json().catch(() => null);

  // Array.isArray, not `?? []`: the guard has to hold against any shape, not
  // just null and undefined. Everything downstream calls .length and .map.
  return Array.isArray(data?.results) ? (data.results as PlaceResult[]) : [];
}
export async function reverseGeocode(lat: number, lng: number): Promise<string> {
  const url = `${API_BASE}/reverse-geocode?lat=${lat}&lng=${lng}`;
  const res = await fetch(url);
  const data = await res.json();
  return data.name || `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
}
export async function getAIRecommendation(
  distanceKm: number,
  routeType: string,
  area: string
): Promise<string> {
  const url = `${API_BASE}/ai-fare-recommendation?distance_km=${distanceKm}&route_type=${routeType}&area=${encodeURIComponent(area)}`;
  const res = await fetch(url);
  const data = await res.json();
  return data.recommendation;
}