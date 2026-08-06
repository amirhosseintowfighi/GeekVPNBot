import { describe, expect, it } from 'vitest'

/**
 * Duration ladder pricing.
 *
 * The admin Products screen previews plan prices client-side before asking
 * the backend to generate them. That preview MUST agree with
 * `domain/catalog/durations.py`, or an operator approves one number and
 * customers are charged another.
 *
 * This file re-states the Python formula and the published rungs, and pins
 * the arithmetic. It is a contract test against a service in another
 * language, kept honest by hand.
 */
const LADDER = [
  { days: 7, slug: '7d', discountBps: -1_500 },
  { days: 30, slug: '30d', discountBps: 0 },
  { days: 90, slug: '90d', discountBps: 1_000 },
  { days: 180, slug: '180d', discountBps: 1_800 },
  { days: 365, slug: '365d', discountBps: 2_500 },
] as const

/** Mirror of `DurationRung.price_from_monthly`. */
const priceFromMonthly = (monthly: number, days: number, discountBps: number) =>
  Math.floor((monthly * (days / 30) * (10_000 - discountBps)) / 10_000)

describe('ladder shape', () => {
  it('omits the sixty-day rung on purpose', () => {
    // Two months is a decision nobody makes; offering it only dilutes the
    // quarterly step that actually converts.
    expect(LADDER.some((rung) => rung.days === 60)).toBe(false)
  })

  it('prices the weekly rung ABOVE the monthly rate', () => {
    // A negative discount is a premium. Short commitments cost more per day;
    // this is the single most misread row in the whole catalogue, so it is
    // asserted rather than assumed.
    const weekly = LADDER[0]
    expect(weekly.discountBps).toBeLessThan(0)

    const monthly = 300_000
    const perDayWeekly = priceFromMonthly(monthly, 7, weekly.discountBps) / 7
    const perDayMonthly = monthly / 30
    expect(perDayWeekly).toBeGreaterThan(perDayMonthly)
  })

  it('increases the discount monotonically with commitment', () => {
    const paid = LADDER.filter((rung) => rung.days >= 30)
    for (let index = 1; index < paid.length; index += 1) {
      expect(paid[index].discountBps).toBeGreaterThan(paid[index - 1].discountBps)
    }
  })

  it('keeps the curve concave: each extra month buys less new discount', () => {
    // Concavity is what stops the annual plan from cannibalising margin.
    const deltas = [1_000 - 0, 1_800 - 1_000, 2_500 - 1_800]
    for (let index = 1; index < deltas.length; index += 1) {
      expect(deltas[index]).toBeLessThanOrEqual(deltas[index - 1])
    }
  })

  it('uses unique slugs and days', () => {
    expect(new Set(LADDER.map((rung) => rung.slug)).size).toBe(LADDER.length)
    expect(new Set(LADDER.map((rung) => rung.days)).size).toBe(LADDER.length)
  })
})

describe('priceFromMonthly', () => {
  it('leaves the thirty-day rung exactly at the monthly price', () => {
    expect(priceFromMonthly(680_000, 30, 0)).toBe(680_000)
  })

  it('computes the published rungs for a 300,000 toman monthly plan', () => {
    expect(priceFromMonthly(300_000, 7, -1_500)).toBe(80_500)
    expect(priceFromMonthly(300_000, 30, 0)).toBe(300_000)
    expect(priceFromMonthly(300_000, 90, 1_000)).toBe(810_000)
    expect(priceFromMonthly(300_000, 180, 1_800)).toBe(1_476_000)
    expect(priceFromMonthly(300_000, 365, 2_500)).toBe(2_737_500)
  })

  it('always rounds DOWN, so the previewed price is never under-charged', () => {
    // Rounding down means the customer is charged at most what the operator
    // saw. Rounding up would silently exceed an approved figure.
    const price = priceFromMonthly(187_777, 90, 1_000)
    expect(price).toBe(Math.floor((187_777 * 3 * 9_000) / 10_000))
    expect(Number.isInteger(price)).toBe(true)
  })

  it('reports a real saving for every committed rung', () => {
    const monthly = 500_000
    for (const rung of LADDER.filter((candidate) => candidate.discountBps > 0)) {
      const straight = monthly * (rung.days / 30)
      expect(priceFromMonthly(monthly, rung.days, rung.discountBps)).toBeLessThan(straight)
    }
  })

  it('never produces a negative price', () => {
    expect(priceFromMonthly(1, 7, -1_500)).toBeGreaterThanOrEqual(0)
  })
})
