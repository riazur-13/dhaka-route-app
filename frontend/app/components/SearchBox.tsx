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
}

export default function SearchBox({ placeholder, onSelect, color, value = '' }: Props) {
  const [query, setQuery] = useState(value);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);

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

    if (query.length < 2) {
      debounceRef.current = setTimeout(() => {
        setResults([]);
        setShowDropdown(false);
      }, 0);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      const data = await searchPlace(query);
      setResults(data);
      setShowDropdown(true);
      setLoading(false);
    }, 400);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

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

        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={placeholder}
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

        {loading && (
          <div style={{
            width: '14px',
            height: '14px',
            border: '2px solid #334155',
            borderTop: `2px solid ${borderColor}`,
            borderRadius: '50%',
            animation: 'spin 0.8s linear infinite',
            flexShrink: 0,
          }} />
        )}
      </div>

      {showDropdown && results.length > 0 && (
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

      {showDropdown && results.length === 0 && !loading && query.length >= 2 && (
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
          padding: '10px 12px',
          fontSize: '13px',
          color: '#94a3b8',
        }}>
          No places found for &quot;{query}&quot;
        </div>
      )}

      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}