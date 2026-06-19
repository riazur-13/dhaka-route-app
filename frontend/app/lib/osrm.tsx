const API_BASE = ' https://dhaka-route-app-4.onrender.com'
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
    distance: data.distance, // metres
    duration: data.duration, // seconds
  };
}
export async function submitFare(
  distanceKm: number,
  fareAmount: number,
  routeType: 'walking' | 'rickshaw'
) {
  const res = await fetch(API_BASE, {
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
  const url = `http://localhost:8000/fares/average?distance_km=${distanceKm}&route_type=${routeType}`;
  const res = await fetch(url);
  return res.json(); // { average_fare, submission_count }
}