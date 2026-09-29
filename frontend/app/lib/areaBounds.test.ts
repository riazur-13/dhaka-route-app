/**
 * Which search results are areas.
 *
 * The frontend's half of the check. The backend only marks a result as an
 * area when it has a box to show, so this is the belt to those braces — and it
 * is what makes a result cached before these fields existed a plain point
 * rather than a crash.
 */

import { describe, expect, it } from 'vitest';
import { areaBounds, type PlaceResult } from './osrm';

const BASE: PlaceResult = {
  name: 'Badda',
  full_name: 'Badda, Dhaka',
  lat: 23.78,
  lng: 90.425,
};

const BOX: [[number, number], [number, number]] = [
  [23.7612, 90.4062],
  [23.797, 90.4486],
];

describe('areaBounds', () => {
  it('returns the box for an area', () => {
    expect(areaBounds({ ...BASE, is_area: true, bbox: BOX })).toEqual(BOX);
  });

  it('returns null for a point, even one with a box', () => {
    expect(areaBounds({ ...BASE, is_area: false, bbox: BOX })).toBeNull();
  });

  it('returns null for an old-shape result with neither field', () => {
    expect(areaBounds(BASE)).toBeNull();
  });

  it.each([
    ['no box', null],
    ['missing box', undefined],
    ['one corner', [[23.76, 90.4]]],
    ['a corner with one number', [[23.76], [23.79, 90.44]]],
    ['a string in it', [['23.76', 90.4], [23.79, 90.44]]],
    ['NaN in it', [[Number.NaN, 90.4], [23.79, 90.44]]],
    ['south above north', [[23.79, 90.4], [23.76, 90.44]]],
    ['west beyond east', [[23.76, 90.44], [23.79, 90.4]]],
  ])('falls back to a point on %s', (_label, bbox) => {
    expect(
      areaBounds({ ...BASE, is_area: true, bbox: bbox as PlaceResult['bbox'] }),
    ).toBeNull();
  });

  it('only a literal true counts', () => {
    // A truthy string from a malformed body is not a yes.
    expect(
      areaBounds({ ...BASE, is_area: 'yes' as unknown as boolean, bbox: BOX }),
    ).toBeNull();
  });
});
