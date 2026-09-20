'use client';

import { useState, useEffect, useRef } from 'react';
import { searchPlace } from '../lib/osrm';

interface SearchResult {
  name: string;
  full_name: string;
  lat: number;
  lng: number;
}

interface Props {
  placeholder: string;
  onSelect: (lat: number, lng: number, name: string) => void;
  color: string;
  value?: string; // ← new prop to control value from outside
  pending?: boolean; // a place name is being looked up for this box
}

/**
 * Does this query contain Bengali characters? U+0980–U+09FF is the Bengali block.
 *
 * A regex rather than a language-detection library, because the question is
 * exactly "are any of these characters Bengali" and the Unicode range answers
 * it outright. A library would be a dependency for a decision already made.
 *
 * Any match counts, so mixed input takes the Bengali branch. That is the
 * intent: someone who typed even one Bengali character does not need to be
 * told the script exists.
 */
const CONTAINS_BENGALI = /[ঀ-৿]/;

/**
 * How long to wait after the last keystroke before asking upstream.
 *
 * Nominatim allows one request a second and has blocked this service's IP
 * range once already, so this is not a polish setting — it is most of what
 * makes search-as-you-type legal to point at them. At a normal typing speed of
 * 150-250ms a character the gap never opens mid-word, so a nine-letter place
 * name costs one request rather than seven.
 */
const DEBOUNCE_MS = 300;

/**
 * Shorter than this and nothing is sent at all.
 *
 * Two characters match half of Dhaka and spend a request finding that out.
 * Three is the point where a query starts to mean something, in either script.
 */
const MIN_QUERY_LENGTH = 3;

export default function SearchBox({ placeholder, onSelect, color, value = '', pending = false }: Props) {
  const [query, setQuery] = useState(value);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);

  // The query the current `results` actually answer.
  //
  // Loading is derived from this rather than stored, which is what lets the
  // dropdown say "working" the instant a key is pressed. Setting a loading
  // flag synchronously in the effect below would do the same thing and is what
  // this component used to do, but React's lint rule rejects it for good
  // reason: a setState in an effect body schedules a second render for
  // something already knowable during the first.
  const [resultsFor, setResultsFor] = useState<string | null>(null);

  // Why the last search came back empty. An empty list on its own cannot say:
  // "nothing matched" and "we could not ask" look identical from the results
  // array, and they need opposite advice.
  const [searchError, setSearchError] = useState<string | null>(null);

  // One in-flight search at a time; the rest are aborted. Same pattern as the
  // geocode and route controllers in map.tsx.
  const searchAbort = useRef<AbortController | null>(null);

  const longEnough = query.length >= MIN_QUERY_LENGTH;

  // Known during render: the query is worth searching and the results on hand
  // are for some older query, so an answer is still coming.
  const loading = longEnough && resultsFor !== query;

  // Update input when parent sets a new value (e.g. from map click)
 const isExternalUpdate = useRef(false);

  // When parent updates value (map click), sync to query without triggering search
  useEffect(() => {
    if (value !== query) {
      isExternalUpdate.current = true;
      setTimeout(() => setQuery(value), 0);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  // Search effect — only triggers on user typing, not external updates
  useEffect(() => {
    if (isExternalUpdate.current) {
      isExternalUpdate.current = false;
      return;
    }

    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (!longEnough) {
      debounceRef.current = setTimeout(() => {
        // Anything in flight is for a query the user has backspaced away from.
        searchAbort.current?.abort();
        searchAbort.current = null;
        setResults([]);
        setResultsFor(null);
        setSearchError(null);
        setShowDropdown(false);
      }, 0);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      // One search in flight at a time. Without this, two requests started a
      // keystroke apart can finish in the other order, and the older, shorter
      // query's results end up on screen under the newer query's text.
      searchAbort.current?.abort();
      const controller = new AbortController();
      searchAbort.current = controller;

      const outcome = await searchPlace(query, controller.signal);

      // Cancelled: a newer keystroke owns the dropdown and the error now, so
      // this one touches neither — and says nothing, because the user typing
      // again is not a failure. `loading` stays true on its own, since the
      // newer query still has no results of its own yet.
      if (outcome === null || searchAbort.current !== controller) return;

      searchAbort.current = null;
      setResults(outcome.places);
      setSearchError(outcome.ok ? null : outcome.message ?? 'Place search is unavailable right now.');
      // Last, and it is what turns `loading` off: results now answer this
      // exact query.
      setResultsFor(query);
    }, DEBOUNCE_MS);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, longEnough]);

  function handleSelect(result: SearchResult) {
    setQuery(result.name);
    setShowDropdown(false);
    onSelect(result.lat, result.lng, result.name);
  }

  const borderColor = color === 'green' ? '#22c55e' : '#f59e0b';
  const dotColor = color === 'green' ? '#22c55e' : '#f59e0b';

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <div style={{
          width: '12px',
          height: '12px',
          borderRadius: '50%',
          background: dotColor,
          flexShrink: 0,
        }} />

        <div style={{ position: 'relative', flex: 1, display: 'flex' }}>
          <input
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              // Opened here rather than in the search effect, because this is
              // a user event and that is where setState belongs. It also opens
              // on the keystroke itself, so the dropdown is already showing
              // its loading state before any request is even sent.
              if (e.target.value.length >= MIN_QUERY_LENGTH) setShowDropdown(true);
            }}
            placeholder={pending ? '' : placeholder}
            style={{
              width: '100%',
              padding: '8px 12px',
              borderRadius: '8px',
              border: `1px solid ${borderColor}40`,
              background: '#1e293b',
              color: 'white',
              fontSize: '13px',
              outline: 'none',
            }}
            onFocus={() => results.length > 0 && setShowDropdown(true)}
            onBlur={() => setTimeout(() => setShowDropdown(false), 200)}
          />

          {/* A pulsing bar where the name will land. Deliberately wordless —
              a Bangla UI is planned, and a shape needs no translation. The
              placeholder is blanked above so the two do not overlap. */}
          {pending && (
            <div
              aria-hidden="true"
              style={{
                position: 'absolute',
                left: '12px',
                right: '12px',
                top: '50%',
                transform: 'translateY(-50%)',
                height: '9px',
                borderRadius: '4px',
                background: '#475569',
                animation: 'skeletonPulse 1.4s ease-in-out infinite',
                pointerEvents: 'none',
              }}
            />
          )}
        </div>

      </div>

      {/* Loading lives in the dropdown, not beside the input, so the answer
          appears where the user is already looking. It shows from the first
          keystroke past the minimum — through the debounce and the request —
          rather than the dropdown staying shut and then filling all at once. */}
      {showDropdown && loading && (
        <div
          role="status"
          style={{
            position: 'absolute',
            top: '100%',
            left: '0',
            right: '0',
            marginTop: '4px',
            background: '#1e293b',
            border: '1px solid #334155',
            borderRadius: '8px',
            zIndex: 2000,
            padding: '10px 12px',
            fontSize: '13px',
            color: '#64748b',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <span
            aria-hidden="true"
            style={{
              width: '12px',
              height: '12px',
              border: '2px solid #334155',
              borderTop: `2px solid ${borderColor}`,
              borderRadius: '50%',
              animation: 'spin 0.8s linear infinite',
              flexShrink: 0,
            }}
          />
          <span style={{ fontFamily: '"Noto Sans Bengali", sans-serif' }}>
            খোঁজা হচ্ছে…
          </span>
        </div>
      )}

      {showDropdown && !loading && results.length > 0 && (
        <div style={{
          position: 'absolute',
          top: '100%',
          left: '0',
          right: '0',
          marginTop: '4px',
          background: '#1e293b',
          border: '1px solid #334155',
          borderRadius: '8px',
          zIndex: 2000,
          overflow: 'hidden',
          boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
        }}>
          {results.map((result, index) => (
            <div
              key={index}
              onMouseDown={() => handleSelect(result)}
              style={{
                padding: '10px 12px',
                cursor: 'pointer',
                borderBottom: index < results.length - 1 ? '1px solid #334155' : 'none',
                fontSize: '13px',
                color: 'white',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = '#334155')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              <p style={{ fontWeight: 600, marginBottom: '2px' }}>{result.name}</p>
              <p style={{ color: '#94a3b8', fontSize: '11px' }}>{result.full_name}</p>
            </div>
          ))}
        </div>
      )}

      {/* Only after a search has actually completed and come back empty.
          `loading` being derived from resultsFor is what guarantees that: it
          stays true until results answer this exact query, so the message
          cannot flash mid-type on stale results. */}
      {showDropdown && !loading && results.length === 0 && longEnough && (
        <div style={{
          position: 'absolute',
          top: '100%',
          left: '0',
          right: '0',
          marginTop: '4px',
          background: '#1e293b',
          border: `1px solid ${searchError ? '#ef4444' : '#334155'}`,
          borderRadius: '8px',
          zIndex: 2000,
          padding: '10px 12px',
          fontSize: '13px',
          color: '#94a3b8',
        }}>
          {searchError ? (
            // An outage, not a spelling problem. Suggesting anything about
            // spelling here would send the user chasing something that is not
            // theirs to fix. Stays outermost: an error is an error whatever
            // script it was typed in.
            <span>{searchError}</span>
          ) : CONTAINS_BENGALI.test(query) ? (
            // They typed Bengali and still got nothing, so the place is not in
            // OpenStreetMap under that name and no spelling will conjure it up.
            // Telling them to try Bengali — which the other branch does — would
            // be the app failing to read its own input, and would send them
            // round in a circle.
            //
            // A map tap is the way through: it sets the point directly and
            // routes normally, with no search in the path at all.
            <span
              style={{
                fontFamily: '"Noto Sans Bengali", sans-serif',
                lineHeight: 1.6,
                display: 'block',
              }}
            >
              &quot;{query}&quot; — এই নামে মানচিত্রে কিছু পাওয়া যায়নি। মানচিত্রে
              জায়গাটির উপর ট্যাপ করে বেছে নিন, রুট ঠিকই বের হবে।
            </span>
          ) : (
            // Latin input, no results. Usually a transliteration mismatch
            // rather than a missing place: OpenStreetMap stores one English
            // spelling per place, so বরুয়া is filed as "Borua" and "Barua"
            // matches nothing. The Bengali spelling is the unambiguous one, so
            // it is worth asking for — here, where it is actually useful.
            <span
              style={{
                fontFamily: '"Noto Sans Bengali", sans-serif',
                lineHeight: 1.6,
                display: 'block',
              }}
            >
              &quot;{query}&quot; খুঁজে পাওয়া যায়নি। জায়গার নাম বাংলায় লিখে দেখুন।
            </span>
          )}
        </div>
      )}

      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
        @keyframes skeletonPulse {
          0%, 100% { opacity: 0.35; }
          50% { opacity: 0.8; }
        }
        @media (prefers-reduced-motion: reduce) {
          @keyframes skeletonPulse {
            0%, 100% { opacity: 0.55; }
          }
        }
      `}</style>
    </div>
  );
}