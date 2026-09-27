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

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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

/** Type enough to clear the 3-character minimum and trip the 300 ms debounce. */
async function search(
  user: ReturnType<typeof userEvent.setup>,
  query: string = QUERY,
) {
  await user.type(screen.getByRole('combobox'), query);
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

describe('what reaches Nominatim', () => {
  // Nominatim allows one request a second and has blocked this service once.
  // These are the assertions that keep autocomplete on the right side of that.

  beforeEach(() => {
    searchPlace.mockResolvedValue({ ok: true, places: [] });
  });

  it('sends nothing below three characters', async () => {
    const user = userEvent.setup();
    renderBox();

    await user.type(screen.getByRole('combobox'), 'Dh');

    // Well past the 300ms debounce, so this is "never sent", not "not yet".
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(searchPlace).not.toHaveBeenCalled();
  });

  it('sends nothing below three characters of Bengali either', async () => {
    const user = userEvent.setup();
    renderBox();

    await user.type(screen.getByRole('combobox'), 'ঢা');

    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(searchPlace).not.toHaveBeenCalled();
  });

  it('sends once for a word typed at speed, not once per keystroke', async () => {
    // delay: null types every character in one go, which is the worst case the
    // debounce exists for: nine keystrokes, seven of them past the minimum.
    const user = userEvent.setup({ delay: null });
    renderBox();

    await user.type(screen.getByRole('combobox'), 'Dhanmondi');
    await waitFor(() => expect(searchPlace).toHaveBeenCalledTimes(1), {
      timeout: 3000,
    });

    // And it stays one — nothing trailing arrives after the debounce settles.
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(searchPlace).toHaveBeenCalledTimes(1);
    expect(searchPlace.mock.calls[0][0]).toBe('Dhanmondi');
  });

  it('aborts the previous request when the query changes', async () => {
    // Hold the first request open so there is something to cancel.
    let release: (v: unknown) => void = () => {};
    searchPlace.mockImplementationOnce(
      () => new Promise((resolve) => { release = resolve; }),
    );

    const user = userEvent.setup({ delay: null });
    renderBox();

    await user.type(screen.getByRole('combobox'), 'Dhan');
    await waitFor(() => expect(searchPlace).toHaveBeenCalledTimes(1), {
      timeout: 3000,
    });

    const firstSignal = searchPlace.mock.calls[0][1] as AbortSignal;
    expect(firstSignal).toBeInstanceOf(AbortSignal);
    expect(firstSignal.aborted).toBe(false);

    searchPlace.mockResolvedValue({ ok: true, places: [] });
    await user.type(screen.getByRole('combobox'), 'mondi');

    await waitFor(() => expect(firstSignal.aborted).toBe(true), { timeout: 3000 });
    release(null);
  });
});

describe('the dropdown while a search is in flight', () => {
  it('shows a loading state rather than opening blank or late', async () => {
    let release: (v: unknown) => void = () => {};
    searchPlace.mockImplementationOnce(
      () => new Promise((resolve) => { release = resolve; }),
    );

    const user = userEvent.setup({ delay: null });
    renderBox();
    await user.type(screen.getByRole('combobox'), 'Dhan');

    // Visible immediately on the keystroke — before the debounce has even run,
    // let alone the request. Asserted while searchPlace has still not been
    // called at all, which is the whole point: the dropdown does not wait.
    expect(await screen.findByRole('status')).toBeDefined();
    expect(screen.getByText('খোঁজা হচ্ছে…')).toBeDefined();
    expect(searchPlace).not.toHaveBeenCalled();

    // Now let the debounce fire, so there is a real promise to release.
    await waitFor(() => expect(searchPlace).toHaveBeenCalledTimes(1), {
      timeout: 3000,
    });
    expect(await screen.findByRole('status')).toBeDefined();

    release({ ok: true, places: [] });
    await waitFor(() => expect(screen.queryByRole('status')).toBeNull(), {
      timeout: 3000,
    });
  });

  it('does not show the empty message while still searching', async () => {
    let release: (v: unknown) => void = () => {};
    searchPlace.mockImplementationOnce(
      () => new Promise((resolve) => { release = resolve; }),
    );

    const user = userEvent.setup({ delay: null });
    renderBox();
    await user.type(screen.getByRole('combobox'), 'Barua');

    await screen.findByRole('status');
    await waitFor(() => expect(searchPlace).toHaveBeenCalledTimes(1), {
      timeout: 3000,
    });

    // The message must wait for an answer. Showing it mid-flight would tell
    // the user nothing was found while the search is still running.
    expect(screen.queryByText(TRY_BENGALI)).toBeNull();

    release({ ok: true, places: [] });
    expect(await screen.findByText(TRY_BENGALI)).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// The keyboard.
//
// Enter is the reflex. Someone types "Gulshan", presses Enter, sees nothing
// happen and concludes the app is broken — and on a phone the dropdown can sit
// behind the keyboard, which makes Enter the comfortable path, not a shortcut.
// ---------------------------------------------------------------------------

const GULSHAN_PLACES = [
  { name: 'Gulshan 1', full_name: 'Gulshan 1, Dhaka', lat: 23.78, lng: 90.416 },
  { name: 'Gulshan 2', full_name: 'Gulshan 2, Dhaka', lat: 23.794, lng: 90.414 },
  { name: 'Gulshan Lake', full_name: 'Gulshan Lake, Dhaka', lat: 23.788, lng: 90.42 },
];

const GUL_PLACES = [
  { name: 'Gulistan', full_name: 'Gulistan, Dhaka', lat: 23.723, lng: 90.412 },
];

/** A search that stays in flight until the test says otherwise. */
function holdNextSearch() {
  let release: (v: unknown) => void = () => {};
  searchPlace.mockImplementationOnce(
    () => new Promise((resolve) => { release = resolve; }),
  );
  return (v: unknown) => release(v);
}

/** Long enough past the debounce that "not called" means never, not not-yet. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 600));

function renderPicker() {
  const onSelect = vi.fn();
  render(<SearchBox placeholder="From" color="green" onSelect={onSelect} />);
  return { onSelect, box: screen.getByRole('combobox') };
}

describe('Enter picks from the dropdown', () => {
  beforeEach(() => {
    // The default for any search a test does not set up — including the one
    // that fires for the picked name after a selection.
    searchPlace.mockResolvedValue({ ok: true, places: GULSHAN_PLACES });
  });

  it('selects the first result when results are showing', async () => {
    const user = userEvent.setup({ delay: null });
    const { onSelect, box } = renderPicker();

    await user.type(box, 'Gulshan');
    await screen.findByRole('listbox');
    const searchesBefore = searchPlace.mock.calls.length;
    await user.keyboard('{Enter}');

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(23.78, 90.416, 'Gulshan 1');
    // Picked from what was on screen: no fresh request stood between the
    // keypress and the pick, so the top result cannot have changed under it.
    expect(searchPlace.mock.calls.length).toBe(searchesBefore);
  });

  it('selects the second result after ArrowDown', async () => {
    const user = userEvent.setup({ delay: null });
    const { onSelect, box } = renderPicker();

    await user.type(box, 'Gulshan');
    await screen.findByRole('listbox');
    await user.keyboard('{ArrowDown}{Enter}');

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(23.794, 90.414, 'Gulshan 2');
  });

  it('points aria-activedescendant at the highlighted option', async () => {
    const user = userEvent.setup({ delay: null });
    const { box } = renderPicker();

    await user.type(box, 'Gulshan');
    await screen.findByRole('listbox');

    const options = screen.getAllByRole('option');
    expect(box.getAttribute('aria-expanded')).toBe('true');
    expect(box.getAttribute('aria-activedescendant')).toBe(options[0].id);
    expect(options[0].getAttribute('aria-selected')).toBe('true');

    await user.keyboard('{ArrowDown}');

    expect(box.getAttribute('aria-activedescendant')).toBe(options[1].id);
    expect(options[1].getAttribute('aria-selected')).toBe('true');
    expect(options[0].getAttribute('aria-selected')).toBe('false');
  });

  it('waits for results when pressed while loading, then selects the first', async () => {
    const release = holdNextSearch();
    const user = userEvent.setup({ delay: null });
    const { onSelect, box } = renderPicker();

    await user.type(box, 'Gulshan');
    await user.keyboard('{Enter}');

    // Still in flight: nothing to pick yet, and the keypress is not lost.
    await waitFor(() => expect(searchPlace).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(onSelect).not.toHaveBeenCalled();

    release({ ok: true, places: GULSHAN_PLACES });

    await waitFor(() => expect(onSelect).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(onSelect).toHaveBeenCalledWith(23.78, 90.416, 'Gulshan 1');
  });

  it('does not select a result belonging to a previous query', async () => {
    // The stale-result trap. "Gul" results are on screen, the user types
    // "shan" and presses Enter before "Gulshan" results land. Gulistan is the
    // first thing visible and the wrong place entirely.
    searchPlace.mockResolvedValueOnce({ ok: true, places: GUL_PLACES });
    const user = userEvent.setup({ delay: null });
    const { onSelect, box } = renderPicker();

    await user.type(box, 'Gul');
    expect(await screen.findByText('Gulistan')).toBeDefined();

    const release = holdNextSearch();
    await user.type(box, 'shan');
    await user.keyboard('{Enter}');

    await waitFor(() => expect(searchPlace).toHaveBeenCalledTimes(2), { timeout: 3000 });
    expect(onSelect).not.toHaveBeenCalled();

    // And the Enter was not dropped: it resolves against the right query.
    release({ ok: true, places: GULSHAN_PLACES });
    await waitFor(() => expect(onSelect).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(onSelect).toHaveBeenCalledWith(23.78, 90.416, 'Gulshan 1');
    expect(onSelect).not.toHaveBeenCalledWith(23.723, 90.412, 'Gulistan');
  });

  it('does not pick the old list after backspacing below the minimum', async () => {
    // The narrower half of the stale-result trap. Under three characters
    // nothing is loading, yet the previous list is still in state until the
    // cleanup runs — so "not loading" is not the same as "these results are
    // for what is typed".
    searchPlace.mockResolvedValueOnce({ ok: true, places: GUL_PLACES });
    const user = userEvent.setup({ delay: null });
    const { onSelect, box } = renderPicker();

    await user.type(box, 'Gul');
    expect(await screen.findByText('Gulistan')).toBeDefined();

    await user.type(box, '{Backspace}{Enter}');
    await settle();

    expect(onSelect).not.toHaveBeenCalled();
  });

  it('a waiting Enter calls the onSelect the parent passes now, not then', async () => {
    // The pick lands after the render that started it. map.tsx's handler reads
    // the other endpoint from its own render, so calling the old one would
    // route from a start point that has since changed — or not route at all.
    const release = holdNextSearch();
    const user = userEvent.setup({ delay: null });
    const before = vi.fn();
    const after = vi.fn();
    const { rerender } = render(
      <SearchBox placeholder="To" color="amber" onSelect={before} />,
    );

    await user.type(screen.getByRole('combobox'), 'Gulshan');
    await user.keyboard('{Enter}');
    await waitFor(() => expect(searchPlace).toHaveBeenCalledTimes(1), { timeout: 3000 });

    // Meanwhile the parent re-renders — say the user tapped a start point.
    rerender(<SearchBox placeholder="To" color="amber" onSelect={after} />);
    release({ ok: true, places: GULSHAN_PLACES });

    await waitFor(() => expect(after).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(before).not.toHaveBeenCalled();
  });

  it('forgets a waiting Enter once the user types again', async () => {
    // Type "Gulshan", Enter, type "x", backspace. The query reads "Gulshan"
    // again, but typing after Enter abandoned it — a rule that only compared
    // queries would still fire the pick when the new results landed.
    const release = holdNextSearch();
    const user = userEvent.setup({ delay: null });
    const { onSelect, box } = renderPicker();

    await user.type(box, 'Gulshan');
    await user.keyboard('{Enter}');
    await waitFor(() => expect(searchPlace).toHaveBeenCalledTimes(1), { timeout: 3000 });

    await user.type(box, 'x{Backspace}');
    release(null); // the first request, now aborted

    await waitFor(() => expect(searchPlace).toHaveBeenCalledTimes(2), { timeout: 3000 });
    expect(await screen.findByRole('listbox')).toBeDefined();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('selects nothing when there are no results', async () => {
    searchPlace.mockResolvedValue({ ok: true, places: [] });
    const user = userEvent.setup({ delay: null });
    const { onSelect, box } = renderPicker();

    await user.type(box, 'Barua');
    await screen.findByText(TRY_BENGALI);
    await user.keyboard('{Enter}');
    await settle();

    expect(onSelect).not.toHaveBeenCalled();
    // The explanation stays where it was.
    expect(screen.getByText(TRY_BENGALI)).toBeDefined();
  });

  it('is ignored while a Bengali word is still being composed', async () => {
    // On many Bengali keyboards Enter is what commits the word being built.
    // Treating that as a pick would choose a suggestion for half-typed text.
    const user = userEvent.setup({ delay: null });
    const { onSelect, box } = renderPicker();

    await user.type(box, 'Gulshan');
    await screen.findByRole('listbox');

    fireEvent.keyDown(box, { key: 'Enter', isComposing: true });
    fireEvent.keyDown(box, { key: 'Enter', keyCode: 229 });
    expect(onSelect).not.toHaveBeenCalled();

    // Not a vacuous pass: the same list, the same key, outside composition.
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});

describe('Escape', () => {
  it('closes the dropdown', async () => {
    searchPlace.mockResolvedValue({ ok: true, places: GULSHAN_PLACES });
    const user = userEvent.setup({ delay: null });
    const { onSelect, box } = renderPicker();

    await user.type(box, 'Gulshan');
    await screen.findByRole('listbox');

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('listbox')).toBeNull();
    expect(box.getAttribute('aria-expanded')).toBe('false');
    expect(box.getAttribute('aria-activedescendant')).toBeNull();
    expect(onSelect).not.toHaveBeenCalled();
  });
});

describe('start and destination together', () => {
  it('each box answers Enter for itself', async () => {
    searchPlace.mockResolvedValue({ ok: true, places: GULSHAN_PLACES });
    const fromSelect = vi.fn();
    const toSelect = vi.fn();
    render(
      <>
        <SearchBox placeholder="From" color="green" onSelect={fromSelect} />
        <SearchBox placeholder="To" color="amber" onSelect={toSelect} />
      </>,
    );
    const from = screen.getByRole('combobox', { name: 'From' });
    const to = screen.getByRole('combobox', { name: 'To' });

    // aria-activedescendant has to point into the right list.
    expect(from.getAttribute('aria-controls')).not.toBe(to.getAttribute('aria-controls'));

    const user = userEvent.setup({ delay: null });
    await user.type(to, 'Gulshan');
    await screen.findByRole('listbox');
    await user.keyboard('{ArrowDown}{Enter}');

    expect(toSelect).toHaveBeenCalledWith(23.794, 90.414, 'Gulshan 2');
    expect(fromSelect).not.toHaveBeenCalled();
  });
});
