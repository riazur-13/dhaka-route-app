/**
 * What the box says when it finds nothing.
 *
 * It used to say "No places found for X" whatever had happened, and that was
 * usually a lie twice over. The place generally exists — OpenStreetMap stores
 * one English transliteration per place, so বরুয়া is filed as "Borua" and
 * "Barua" matches nothing. And when Nominatim is down, nothing was searched at
 * all, so advising a different spelling sends the user chasing a problem that
 * is not theirs.
 *
 * Two outcomes, two messages, and the distinction has to survive: an empty
 * array cannot tell them apart on its own.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const searchPlace = vi.fn();

vi.mock('../lib/osrm', () => ({
  searchPlace: (...args: unknown[]) => searchPlace(...args),
}));

const { default: SearchBox } = await import('./SearchBox');

const QUERY = 'Barua';

function renderBox() {
  return render(
    <SearchBox placeholder="From" color="green" onSelect={() => {}} />,
  );
}

/** Type enough to clear the 2-character minimum and trip the 400 ms debounce. */
async function search(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByRole('textbox'), QUERY);
  await waitFor(() => expect(searchPlace).toHaveBeenCalled(), { timeout: 3000 });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('a genuinely empty result set', () => {
  beforeEach(() => {
    searchPlace.mockResolvedValue({ ok: true, places: [] });
  });

  it('asks for the Bengali spelling', async () => {
    const user = userEvent.setup();
    renderBox();
    await search(user);

    expect(
      await screen.findByText(/জায়গার নাম বাংলায় লিখে দেখুন/),
    ).toBeDefined();
  });

  it('echoes back what was typed, so the user can see what failed', async () => {
    const user = userEvent.setup();
    renderBox();
    await search(user);

    const message = await screen.findByText(/বাংলায় লিখে দেখুন/);
    expect(message.textContent).toContain(QUERY);
  });

  it('renders it in the Bengali font stack', async () => {
    const user = userEvent.setup();
    renderBox();
    await search(user);

    const message = await screen.findByText(/বাংলায় লিখে দেখুন/);
    expect(message.getAttribute('style')).toContain('Noto Sans Bengali');
  });

  it('no longer claims the place does not exist', async () => {
    const user = userEvent.setup();
    renderBox();
    await search(user);

    await screen.findByText(/বাংলায় লিখে দেখুন/);
    expect(screen.queryByText(/No places found/)).toBeNull();
  });
});

describe('an upstream failure', () => {
  beforeEach(() => {
    searchPlace.mockResolvedValue({
      ok: false,
      places: [],
      message: 'Place search is unavailable right now.',
    });
  });

  it('says the service is down', async () => {
    const user = userEvent.setup();
    renderBox();
    await search(user);

    expect(
      await screen.findByText(/Place search is unavailable right now/),
    ).toBeDefined();
  });

  it('does NOT suggest trying Bengali', async () => {
    const user = userEvent.setup();
    renderBox();
    await search(user);

    await screen.findByText(/unavailable right now/);
    // The whole point of carrying `ok` separately. Nothing was searched, so a
    // spelling suggestion would be advice about the wrong problem.
    expect(screen.queryByText(/বাংলায় লিখে দেখুন/)).toBeNull();
  });
});

describe('when there are results', () => {
  it('shows neither message', async () => {
    searchPlace.mockResolvedValue({
      ok: true,
      places: [
        { name: 'Borua', full_name: 'Borua, Dhaka', lat: 23.81, lng: 90.41 },
      ],
    });

    const user = userEvent.setup();
    renderBox();
    await search(user);

    expect(await screen.findByText('Borua')).toBeDefined();
    expect(screen.queryByText(/বাংলায় লিখে দেখুন/)).toBeNull();
    expect(screen.queryByText(/unavailable right now/)).toBeNull();
  });
});
