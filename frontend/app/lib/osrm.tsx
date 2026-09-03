const API_BASE = 'https://dhaka-route-app-4.onrender.com'; // ✅ no space

export interface RouteSuccess {
  coordinates: [number, number][];
  distance: number;
  duration: number;
}

export interface RouteResult {
  ok: boolean;
  route: RouteSuccess | null;
  message?: string;
}

const UNREACHABLE = 'Could not reach the server. Check your connection and try again.';

export async function fetchRoute(
  start: [number, number],
  end: [number, number]
): Promise<RouteResult> {
  const url = `${API_BASE}/route?start_lat=${start[0]}&start_lng=${start[1]}&end_lat=${end[0]}&end_lng=${end[1]}`;
  let res: Response;

  try {
    res = await fetch(url);
  } catch {
    return { ok: false, route: null, message: UNREACHABLE };
  }

  const data = await res.json().catch(() => null);

  if (!res.ok) {
    // The backend sends a plain-string `detail`: "Route not found" for a 400,
    // or the OSRM-unavailable message for a 502. FastAPI's own 422 sends an
    // array instead, which is not something to put in front of a user.
    const detail = typeof data?.detail === 'string' ? data.detail : null;
    return { ok: false, route: null, message: detail || 'Could not find a route between those two points.' };
  }

  // A 200 that is not the documented shape is still a failure, and used to
  // return null here — indistinguishable from an error, and silent either way.
  if (!Array.isArray(data?.coordinates)) {
    return { ok: false, route: null, message: 'Could not find a route between those two points.' };
  }

  const coordinates = data.coordinates.map(([lng, lat]: [number, number]) => [lat, lng] as [number, number]);

  return {
    ok: true,
    route: {
      coordinates,
      distance: data.distance,
      duration: data.duration,
    },
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

export interface AverageFareResult {
  ok: boolean;
  averageFare: number | null;
  submissionCount: number;
  message?: string;
}

export async function getAverageFare(
  distanceKm: number,
  routeType: 'walking' | 'rickshaw'
): Promise<AverageFareResult> {
  const url = `${API_BASE}/fares/average?distance_km=${distanceKm}&route_type=${routeType}`; // ✅ uses API_BASE
  let res: Response;

  // `ok` is the only thing that separates a failure from a real answer here.
  // The backend sends average_fare: null with submission_count: 0 when nobody
  // has submitted a fare for this distance yet, and that is data — it is how
  // the app knows to say "no submissions" rather than "we could not ask".
  // Reading a null average as an error would report an outage every time a
  // route is new, which is most of them.
  const empty = { averageFare: null, submissionCount: 0 };

  try {
    res = await fetch(url);
  } catch {
    return { ok: false, ...empty, message: UNREACHABLE };
  }

  const data = await res.json().catch(() => null);

  if (!res.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : null;
    return { ok: false, ...empty, message: detail || 'Could not load the crowdsourced fare for this trip.' };
  }

  return {
    ok: true,
    averageFare: typeof data?.average_fare === 'number' ? data.average_fare : null,
    submissionCount: typeof data?.submission_count === 'number' ? data.submission_count : 0,
  };
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
export type GeocodeResult = { name: string; ok: boolean; message?: string };

/** Wakes the backend. Never throws, never reports, never returns anything. */
export async function pingHealth(): Promise<void> {
  try {
    await fetch(`${API_BASE}/health`);
  } catch {
    // Deliberately empty. This is a courtesy call to start Render's free tier
    // waking before the user's first click; whether it succeeded is not
    // information anyone needs. Failing loudly here would put a red banner on
    // the screen of someone who has not yet done anything.
  }
}

/**
 * Returns null when the lookup was cancelled by its AbortSignal.
 *
 * Null is not a failure and must not be reported as one — it means the caller
 * has already started a newer lookup for the same thing, and that newer one now
 * owns the name, the pending state and the marker. A caller that sees null
 * should do nothing at all.
 */
export async function reverseGeocode(
  lat: number,
  lng: number,
  signal?: AbortSignal
): Promise<GeocodeResult | null> {
  const url = `${API_BASE}/reverse-geocode?lat=${lat}&lng=${lng}`;

  // Always a usable name, whatever happens below. The caller drops a marker on
  // the map either way, and a marker labelled with its own coordinates is a
  // worse label than a street name but not a broken one.
  const coordinateFallback = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
  let res: Response;

  try {
    res = await fetch(url, { signal });
  } catch (error) {
    // An abort arrives here as a thrown error like any other, and it is the one
    // kind that must stay silent: the user clicking a second time is not a
    // network problem and has no business raising a banner. Checking the signal
    // as well as the name because not every runtime throws the same object.
    if (signal?.aborted || (error as Error)?.name === "AbortError") return null;
    return { name: coordinateFallback, ok: false, message: UNREACHABLE };
  }

  const data = await res.json().catch(() => null);

  // The body can be cut off mid-read too, after the headers have arrived. The
  // parse guard above swallows that as a null body, and without this check we
  // would fall through and answer with a coordinate name from a request the
  // caller abandoned — the exact stale overwrite the signal exists to prevent.
  if (signal?.aborted) return null;

  if (!res.ok) {
    // 502 when Nominatim is blocked or down, including a cached failure the
    // backend is replaying rather than asking again.
    const detail = typeof data?.detail === 'string' ? data.detail : null;
    return {
      name: coordinateFallback,
      ok: false,
      message: detail || 'Place names are unavailable right now.',
    };
  }

  // ok: true even when `name` reads back as a pair of coordinates. The backend
  // returns exactly that, deliberately, for a spot with no address — open
  // water, an empty field — and that is Nominatim answering, not failing. The
  // shape of the string is not evidence of anything; only the status is.
  return { name: data?.name || coordinateFallback, ok: true };
}
export interface RecommendationResult {
  ok: boolean;
  recommendation: string | null;
  message?: string;
}

export async function getAIRecommendation(
  distanceKm: number,
  routeType: string,
  area: string
): Promise<RecommendationResult> {
  const url = `${API_BASE}/ai-fare-recommendation?distance_km=${distanceKm}&route_type=${routeType}&area=${encodeURIComponent(area)}`;
  let res: Response;

  try {
    res = await fetch(url);
  } catch {
    return { ok: false, recommendation: null, message: UNREACHABLE };
  }

  const data = await res.json().catch(() => null);

  if (!res.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : null;
    return {
      ok: false,
      recommendation: null,
      message: detail || 'Could not load the fare advice for this trip.',
    };
  }

  // A 200 with no usable string is still nothing to render. The backend does
  // send a Bengali fallback sentence of its own when Groq fails, so this only
  // catches a body that is missing the field or has the wrong type in it.
  const recommendation = typeof data?.recommendation === 'string' ? data.recommendation : null;

  return { ok: true, recommendation };
}