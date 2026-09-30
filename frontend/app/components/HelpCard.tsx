"use client";

import { useEffect, useId, useRef, type RefObject } from "react";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // The button, owned by the parent so the map fit can measure it. Used here
  // too, to hand focus back on Escape. The open card is never measured:
  // map.tsx closes it before every fit instead — see showOnMap.
  buttonRef: RefObject<HTMLButtonElement | null>;
}

const BENGALI_FONT = '"Noto Sans Bengali", sans-serif';

/**
 * How to use the app, in the corner where the legend used to be.
 *
 * Collapsed to one small button by default, because it must never cover the
 * map unless someone asks for it. Controlled rather than owning its own state,
 * so the map can close it when it is about to move: an open card sitting over
 * the place just searched for would hide the very thing the move is showing.
 *
 * The legend's "green = walking, orange = rickshaw" is not carried over. Both
 * lines are the same OSRM walking route drawn twice, so the claim was false.
 */
export default function HelpCard({ open, onOpenChange, buttonRef }: Props) {
  const cardId = useId();
  const headingId = useId();
  const cardRef = useRef<HTMLDivElement>(null);

  // Escape closes it from anywhere, not only with focus on the button: someone
  // who opened it and then clicked into the card to read has focus in there.
  useEffect(() => {
    if (!open) return;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      // Focus goes back to the button only if it was inside the card, which is
      // about to disappear and take the focus with it. Focus in a search box
      // stays where the user put it.
      const focusWasInside =
        cardRef.current?.contains(document.activeElement) ?? false;
      onOpenChange(false);
      if (focusWasInside) buttonRef.current?.focus();
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange, buttonRef]);

  return (
    <div
      style={{
        position: "absolute",
        bottom: "32px",
        left: "16px",
        zIndex: 1000,
        display: "flex",
        // Reversed so the card sits visually above the button while coming
        // after it in the DOM: Tab goes button, then card, which is the order
        // someone opening it and then reading it actually wants.
        flexDirection: "column-reverse",
        alignItems: "flex-start",
        gap: "8px",
        fontFamily: BENGALI_FONT,
      }}
    >
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        // Only while the card exists; closed, it is not in the DOM to point at.
        aria-controls={open ? cardId : undefined}
        onClick={() => onOpenChange(!open)}
        style={{
          background: "rgba(15,23,42,0.9)",
          border: "1px solid #334155",
          borderRadius: "999px",
          color: "white",
          cursor: "pointer",
          fontFamily: BENGALI_FONT,
          fontSize: "14px",
          lineHeight: 1.4,
          padding: "8px 14px",
          backdropFilter: "blur(8px)",
        }}
      >
        সাহায্য ?
      </button>

      {open && (
        <div
          ref={cardRef}
          id={cardId}
          role="region"
          aria-labelledby={headingId}
          // Focusable because it scrolls. On a small phone it is taller than
          // the space it has, and a keyboard user can only scroll a region
          // they can put focus in. That is also what makes Escape's
          // focus-return below reachable: without it, nothing in the card
          // could ever hold focus.
          tabIndex={0}
          style={{
            // 320 wide, but never wider than the screen less the 16px gutter
            // either side, so a narrow phone gets no sideways scroll.
            width: "320px",
            maxWidth: "calc(100vw - 32px)",
            // Taller than a small phone's free space, so it scrolls inside
            // itself rather than running off the top of the screen.
            maxHeight: "calc(100vh - 140px)",
            overflowY: "auto",
            boxSizing: "border-box",
            background: "rgba(15,23,42,0.95)",
            border: "1px solid #334155",
            borderRadius: "12px",
            backdropFilter: "blur(8px)",
            padding: "14px 16px",
            color: "#e2e8f0",
            fontSize: "14px",
            lineHeight: 1.7,
          }}
        >
          <h2
            id={headingId}
            style={{ margin: "0 0 6px", fontSize: "15px", color: "white" }}
          >
            কীভাবে ব্যবহার করবেন
          </h2>
          <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
            <li>১. শুরুর জায়গা লিখুন বা ম্যাপে ট্যাপ করুন।</li>
            <li>২. গন্তব্য লিখুন বা ম্যাপে ট্যাপ করুন।</li>
            <li>৩. প্যাডেল নাকি ব্যাটারি রিকশা, বেছে নিন।</li>
            <li>৪. আনুমানিক ভাড়া দেখে দরদাম করুন।</li>
            <li>৫. যাত্রা শেষে কত দিলেন, তা জমা দিন।</li>
          </ol>

          <h2
            style={{ margin: "14px 0 6px", fontSize: "15px", color: "white" }}
          >
            জেনে রাখুন
          </h2>
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            <li>• ভাড়া আনুমানিক, নির্ধারিত নয়।</li>
            <li>• ব্যাটারি রিকশার ভাড়া প্যাডেলের চেয়ে কম।</li>
            <li>• বাংলায় লিখলে জায়গা খুঁজে পাওয়া সহজ।</li>
            <li>
              • এলাকার নাম খুঁজলে ম্যাপ সেই এলাকায় যাবে, তারপর সঠিক জায়গায়
              ট্যাপ করুন।
            </li>
          </ul>
        </div>
      )}
    </div>
  );
}
