import { describe, expect, it } from 'vitest'

import { JALALI_MONTHS, toJalali, WEEKDAYS } from '@/lib/jalali'

/**
 * The Jalali conversion is a hand-written port of the algorithm the bot uses.
 * A port is only trustworthy if it is pinned to the same anchors as the
 * original, so these are the exact dates asserted in the Python suite.
 *
 * If one of these fails, the calendar is off by a day or a year somewhere and
 * every expiry date in the product is wrong.
 *
 * Note the return shape: `toJalali` returns a [year, month, day] tuple, not an
 * object, matching the Python helper it was ported from.
 */
describe('toJalali', () => {
  it('maps Nowruz 2026 to the first day of 1405', () => {
    expect(toJalali(new Date(Date.UTC(2026, 2, 21)))).toEqual([1405, 1, 1])
  })

  it('maps the day before Nowruz to the last month of 1404', () => {
    // The year boundary is the easiest thing to get wrong by one.
    const [year, month] = toJalali(new Date(Date.UTC(2026, 2, 20)))
    expect(year).toBe(1404)
    expect(month).toBe(12)
  })

  it('handles a mid-year date', () => {
    const [year, month] = toJalali(new Date(Date.UTC(2026, 6, 23)))
    expect(year).toBe(1405)
    expect(month).toBe(5)
  })

  it('produces an in-range month and day for every day of a Gregorian year', () => {
    // A cheap property check that catches an off-by-one in the month tables.
    for (let dayOffset = 0; dayOffset < 365; dayOffset += 1) {
      const date = new Date(Date.UTC(2026, 0, 1 + dayOffset))
      const [, month, day] = toJalali(date)
      expect(month).toBeGreaterThanOrEqual(1)
      expect(month).toBeLessThanOrEqual(12)
      expect(day).toBeGreaterThanOrEqual(1)
      expect(day).toBeLessThanOrEqual(31)
    }
  })

  it('advances the Jalali day by one when the Gregorian day advances', () => {
    const [, , first] = toJalali(new Date(Date.UTC(2026, 5, 10)))
    const [, , second] = toJalali(new Date(Date.UTC(2026, 5, 11)))
    expect(second - first).toBe(1)
  })
})

describe('name tables', () => {
  it('has twelve months', () => {
    expect(JALALI_MONTHS).toHaveLength(12)
  })

  it('starts the month list with Farvardin', () => {
    expect(JALALI_MONTHS[0]).toBe('\u0641\u0631\u0648\u0631\u062f\u06cc\u0646')
  })

  it('has seven weekdays', () => {
    // Indexed by Date.prototype.getDay(), where 0 is Sunday, not by the
    // Persian week, which begins on Saturday.
    expect(WEEKDAYS).toHaveLength(7)
  })
})
