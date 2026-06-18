const API_BASE = 'https://dhaka-route-app-3.onrender.com'
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