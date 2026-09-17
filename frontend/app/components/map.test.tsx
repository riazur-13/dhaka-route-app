/**
 * The vehicle question comes before the fare.
 *
 * Both fare figures are priced per vehicle, so quoting one before the rider has
 * said which rickshaw they took means quoting a pedal fare to someone who may
 * have taken a battery. That is worse than showing nothing: it is wrong in a way
 * the reader cannot see. These tests pin the ordering down.
 *
 * Leaflet is stubbed rather than run. It wants a real layout engine, and none of
 * what is under test here is about the map — only about what is asked for, when.
 * Stubbing useMapEvents also hands us the click handler directly, which is the
 * only way to simulate a map click without a map.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

type MapClick = (event: { latlng: { lat: number; lng: number } }) => void;

/** Captured from the stubbed useMapEvents so tests can click the "map". */
let mapClick: MapClick;

vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  TileLayer: () => null,
  Marker: () => null,
  Polyline: () => null,
  Popup: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  useMapEvents: (handlers: { click: MapClick }) => {
    mapClick = handlers.click;
    return null;
  },
}));

vi.mock('leaflet', () => ({
  default: { divIcon: () => ({}) },
}));

const fetchRoute = vi.fn();
const getAverageFare = vi.fn();
const getAIRecommendation = vi.fn();
const reverseGeocode = vi.fn();
const submitFare = vi.fn();
const searchPlace = vi.fn();
const pingHealth = vi.fn();

vi.mock('../lib/osrm', () => ({
  fetchRoute: (...args: unknown[]) => fetchRoute(...args),
  getAverageFare: (...args: unknown[]) => getAverageFare(...args),
  getAIRecommendation: (...args: unknown[]) => getAIRecommendation(...args),
  reverseGeocode: (...args: unknown[]) => reverseGeocode(...args),
  submitFare: (...args: unknown[]) => submitFare(...args),
  searchPlace: (...args: unknown[]) => searchPlace(...args),
  pingHealth: (...args: unknown[]) => pingHealth(...args),
}));

// Imported after the mocks so the component picks them up.
const { default: Map } = await import('./map');

const ROUTE = {
  ok: true,
  route: { coordinates: [[23.81, 90.41]], distance: 3000, duration: 900 },
};

beforeEach(() => {
  vi.clearAllMocks();

  reverseGeocode.mockResolvedValue({ name: 'Tejgaon', ok: true });
  fetchRoute.mockResolvedValue(ROUTE);
  getAverageFare.mockResolvedValue({ ok: true, averageFare: 95, submissionCount: 7 });
  getAIRecommendation.mockResolvedValue({ ok: true, recommendation: 'ভাড়া যুক্তিসঙ্গত।' });
  pingHealth.mockResolvedValue(undefined);
});

/** Two map clicks: one to set the start, one to set the end and draw a route. */
async function drawARoute() {
  render(<Map />);

  await waitFor(() => expect(mapClick).toBeTypeOf('function'));

  mapClick({ latlng: { lat: 23.81, lng: 90.41 } });
  await waitFor(() => expect(reverseGeocode).toHaveBeenCalledTimes(1));

  mapClick({ latlng: { lat: 23.78, lng: 90.42 } });
  await waitFor(() => expect(fetchRoute).toHaveBeenCalledTimes(1));
}

function vehicleArgOf(mock: ReturnType<typeof vi.fn>, call: number) {
  // getAverageFare(distanceKm, routeType, vehicleType, signal)
  // getAIRecommendation(distanceKm, routeType, area, vehicleType, signal)
  const args = mock.mock.calls[call];
  return mock === getAverageFare ? args[2] : args[3];
}

describe('before a vehicle is chosen', () => {
  it('asks the question', async () => {
    await drawARoute();

    expect(await screen.findByText('Which rickshaw?')).toBeDefined();
    expect(screen.getByRole('radio', { name: /Pedal/ })).toBeDefined();
    expect(screen.getByRole('radio', { name: /Battery/ })).toBeDefined();
  });

  it('calls neither fare endpoint', async () => {
    await drawARoute();

    // The route itself is fetched — it does not depend on the vehicle.
    expect(fetchRoute).toHaveBeenCalledTimes(1);

    // Neither of these may run. The backend defaults a missing vehicle_type to
    // pedal, and this is what keeps that default unreachable from the UI.
    expect(getAverageFare).not.toHaveBeenCalled();
    expect(getAIRecommendation).not.toHaveBeenCalled();
  });

  it('shows neither a fare nor a vehicle label', async () => {
    await drawARoute();

    expect(await screen.findByText('Which rickshaw?')).toBeDefined();
    expect(screen.queryByText(/৳95 avg/)).toBeNull();
    expect(screen.queryByText('Pedal rickshaw')).toBeNull();
    expect(screen.queryByText('Battery rickshaw')).toBeNull();
  });
});

describe('once a vehicle is chosen', () => {
  it('fetches both figures with the chosen value', async () => {
    const user = userEvent.setup();
    await drawARoute();

    await user.click(await screen.findByRole('radio', { name: /Pedal/ }));

    await waitFor(() => expect(getAverageFare).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(getAIRecommendation).toHaveBeenCalledTimes(1));

    expect(vehicleArgOf(getAverageFare, 0)).toBe('pedal');
    expect(vehicleArgOf(getAIRecommendation, 0)).toBe('pedal');
  });

  it('labels the fare with the vehicle it is priced for', async () => {
    const user = userEvent.setup();
    await drawARoute();

    await user.click(await screen.findByRole('radio', { name: /Pedal/ }));

    expect(await screen.findByText(/৳95 avg/)).toBeDefined();
    // Put next to the figure rather than only on the toggle, so a mis-tap is
    // visible where the reader is already looking.
    expect(await screen.findByText('Pedal rickshaw')).toBeDefined();
  });
});

describe('changing the answer', () => {
  it('refetches both figures for the new vehicle', async () => {
    const user = userEvent.setup();
    await drawARoute();

    await user.click(await screen.findByRole('radio', { name: /Pedal/ }));
    await waitFor(() => expect(getAverageFare).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole('radio', { name: /Battery/ }));

    await waitFor(() => expect(getAverageFare).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(getAIRecommendation).toHaveBeenCalledTimes(2));

    expect(vehicleArgOf(getAverageFare, 1)).toBe('battery');
    expect(vehicleArgOf(getAIRecommendation, 1)).toBe('battery');
  });

  it('relabels the fare', async () => {
    const user = userEvent.setup();
    await drawARoute();

    await user.click(await screen.findByRole('radio', { name: /Pedal/ }));
    expect(await screen.findByText('Pedal rickshaw')).toBeDefined();

    await user.click(screen.getByRole('radio', { name: /Battery/ }));

    expect(await screen.findByText('Battery rickshaw')).toBeDefined();
    expect(screen.queryByText('Pedal rickshaw')).toBeNull();
  });

  it('passes an abort signal, so a fast double-tap cannot land out of order', async () => {
    const user = userEvent.setup();
    await drawARoute();

    await user.click(await screen.findByRole('radio', { name: /Pedal/ }));
    await waitFor(() => expect(getAverageFare).toHaveBeenCalledTimes(1));

    const signal = getAverageFare.mock.calls[0][3];
    expect(signal).toBeInstanceOf(AbortSignal);

    await user.click(screen.getByRole('radio', { name: /Battery/ }));

    // Switching vehicle cancels the pair already in flight for the old one.
    await waitFor(() => expect(signal.aborted).toBe(true));
  });
});
