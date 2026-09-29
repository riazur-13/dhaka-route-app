/**
 * The help card that replaced the legend.
 *
 * Collapsed by default, because it must never cover the map unless someone
 * asks for it. Everything else here is about getting it open and shut again by
 * every route a person might try: a tap, the keyboard, Escape.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useRef, useState } from 'react';
import { describe, expect, it } from 'vitest';
import HelpCard from './HelpCard';

/** The card is controlled; this is the smallest parent that owns its state. */
function Harness({ initiallyOpen = false }: { initiallyOpen?: boolean }) {
  const [open, setOpen] = useState(initiallyOpen);
  const buttonRef = useRef<HTMLButtonElement>(null);
  return (
    <>
      <input aria-label="elsewhere" />
      <HelpCard open={open} onOpenChange={setOpen} buttonRef={buttonRef} />
    </>
  );
}

const HEADING = 'কীভাবে ব্যবহার করবেন';

function button() {
  return screen.getByRole('button', { name: '? সাহায্য' });
}

describe('the help card', () => {
  it('is collapsed by default: a button and nothing else', () => {
    render(<Harness />);

    expect(button().getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByText(HEADING)).toBeNull();
    expect(screen.queryByRole('region')).toBeNull();
  });

  it('is a real button', () => {
    render(<Harness />);

    expect(button().tagName).toBe('BUTTON');
    expect(button().getAttribute('type')).toBe('button');
  });

  it('opens on a tap and closes on the next', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(button());
    expect(button().getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByRole('region', { name: HEADING })).toBeDefined();

    await user.click(button());
    expect(button().getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByText(HEADING)).toBeNull();
  });

  it('points aria-controls at the card while it is open', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    // Closed, there is no card in the DOM to point at.
    expect(button().getAttribute('aria-controls')).toBeNull();

    await user.click(button());
    const card = screen.getByRole('region', { name: HEADING });
    expect(button().getAttribute('aria-controls')).toBe(card.id);
  });

  it('opens from the keyboard', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.tab(); // the other input
    await user.tab(); // the button
    expect(document.activeElement).toBe(button());

    await user.keyboard('{Enter}');
    expect(screen.getByText(HEADING)).toBeDefined();
  });

  it('closes on Escape', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(button());
    expect(button().getAttribute('aria-expanded')).toBe('true');
    await user.keyboard('{Escape}');

    expect(button().getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByText(HEADING)).toBeNull();
  });

  it('can take focus, so a keyboard can scroll it on a small screen', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(button());
    await user.tab();

    // Button first, then the card: the order someone opening it wants.
    expect(document.activeElement).toBe(screen.getByRole('region', { name: HEADING }));
  });

  it('hands focus back to the button when Escape closes it from inside', async () => {
    // The card is about to leave the DOM and would take the focus with it,
    // dropping a keyboard user back at the top of the page.
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(button());
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole('region', { name: HEADING }));

    await user.keyboard('{Escape}');

    expect(screen.queryByText(HEADING)).toBeNull();
    expect(document.activeElement).toBe(button());
  });

  it('closes on Escape without stealing focus from somewhere else', async () => {
    // Opened, then the user went back to typing a place. Escape shuts the
    // card, and their cursor stays in the box.
    const user = userEvent.setup();
    render(<Harness initiallyOpen />);

    const elsewhere = screen.getByRole('textbox', { name: 'elsewhere' });
    await user.click(elsewhere);
    await user.keyboard('{Escape}');

    expect(screen.queryByText(HEADING)).toBeNull();
    expect(document.activeElement).toBe(elsewhere);
  });

  it('says exactly what it was given, minus the line-colour key', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(button());

    for (const line of [
      'কীভাবে ব্যবহার করবেন',
      '১. শুরুর জায়গা লিখুন বা ম্যাপে ট্যাপ করুন।',
      '২. গন্তব্য লিখুন বা ম্যাপে ট্যাপ করুন।',
      '৩. প্যাডেল নাকি ব্যাটারি রিকশা, বেছে নিন।',
      '৪. আনুমানিক ভাড়া দেখে দরদাম করুন।',
      '৫. যাত্রা শেষে কত দিলেন, তা জমা দিন।',
      'জেনে রাখুন',
      '• ভাড়া আনুমানিক, নির্ধারিত নয়।',
      '• ব্যাটারি রিকশার ভাড়া প্যাডেলের চেয়ে কম।',
      '• বাংলায় লিখলে জায়গা খুঁজে পাওয়া সহজ।',
      '• এলাকার নাম খুঁজলে ম্যাপ সেই এলাকায় যাবে, তারপর সঠিক জায়গায় ট্যাপ করুন।',
    ]) {
      expect(screen.getByText(line)).toBeDefined();
    }

    // Both lines on the map are the same walking route drawn twice, so a key
    // calling one of them the rickshaw route would be false.
    expect(screen.queryByText(/রেখা/)).toBeNull();
  });

  it('is set in the Bengali font stack, button included', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(button());

    const card = screen.getByRole('region', { name: HEADING });
    expect(card.parentElement!.getAttribute('style')).toContain('Noto Sans Bengali');
    expect(button().getAttribute('style')).toContain('Noto Sans Bengali');
  });

  it('fits a phone: never wider than the screen, and scrolls if taller', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(button());

    const style = screen.getByRole('region', { name: HEADING }).getAttribute('style')!;
    expect(style).toContain('calc(100vw - 32px)');
    expect(style).toContain('overflow-y: auto');
  });
});
