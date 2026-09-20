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
const BENGALI_QUERY = 'বরুয়া';
const MIXED_QUERY = 'Barua বরুয়া';

/** The advice that must not appear when the user already typed Bengali. */
const TRY_BENGALI = /জায়গার নাম বাংলায় লিখে দেখুন/;
/** The advice that replaces it: drop a pin instead. */
const TAP_THE_MAP = /মানচিত্রে জায়গাটির উপর ট্যাপ করে বেছে নিন/;

function renderBox() {
  return render(
    <SearchBox placeholder="From" color="green" onSelect={() => {}} />,
  );
}

/** Type enough to clear the 2-character minimum and trip the 400 ms debounce. */
async function search(
  user: ReturnType<typeof userEvent.setup>,
  query: string = QUERY,
) {
  await user.type(screen.getByRole('textbox'), query);
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

describe('a Bengali query that finds nothing', () => {
  beforeEach(() => {
    searchPlace.mockResolvedValue({ ok: true, places: [] });
  });

  it('does NOT tell them to try Bengali', async () => {
    const user = userEvent.setup();
    renderBox();
    await search(user, BENGALI_QUERY);

    // The assertion this whole change exists for. Everything else here would
    // still pass if the branch were deleted; this is what catches that.
    await screen.findByText(TAP_THE_MAP);
    expect(screen.queryByText(TRY_BENGALI)).toBeNull();
  });

  it('suggests dropping a pin instead, which routes without search', async () => {
    const user = userEvent.setup();
    renderBox();
    await search(user, BENGALI_QUERY);

    expect(await screen.findByText(TAP_THE_MAP)).toBeDefined();
  });

  it('echoes the query back', async () => {
    const user = userEvent.setup();
    renderBox();
    await search(user, BENGALI_QUERY);

    const message = await screen.findByText(TAP_THE_MAP);
    expect(message.textContent).toContain(BENGALI_QUERY);
  });

  it('uses the Bengali font stack', async () => {
    const user = userEvent.setup();
    renderBox();
    await search(user, BENGALI_QUERY);

    const message = await screen.findByText(TAP_THE_MAP);
    expect(message.getAttribute('style')).toContain('Noto Sans Bengali');
  });

  it('takes the Bengali branch on mixed input too', async () => {
    // One Bengali character is enough. Someone who typed any of it knows the
    // script, so the suggestion has nothing to tell them.
    const user = userEvent.setup();
    renderBox();
    await search(user, MIXED_QUERY);

    expect(await screen.findByText(TAP_THE_MAP)).toBeDefined();
    expect(screen.queryByText(TRY_BENGALI)).toBeNull();
  });
});

describe('an upstream failure outranks the script check', () => {
  it('shows the error even when the query was Bengali', async () => {
    searchPlace.mockResolvedValue({
      ok: false,
      places: [],
      message: 'Place search is unavailable right now.',
    });

    const user = userEvent.setup();
    renderBox();
    await search(user, BENGALI_QUERY);

    // Nothing was searched, so neither piece of spelling advice applies.
    expect(await screen.findByText(/unavailable right now/)).toBeDefined();
    expect(screen.queryByText(TAP_THE_MAP)).toBeNull();
    expect(screen.queryByText(TRY_BENGALI)).toBeNull();
  });
});
