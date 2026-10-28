import { describe, expect, it } from 'vitest'

import { byTerm, monthsIn, termsOf, volumeNote } from '@/lib/plans'
import type { PlanCard } from '@/lib/types'

const plan = (over: Partial<PlanCard>): PlanCard => ({
  planId: 'p',
  productId: 'x',
  nameFa: '',
  planType: 'traffic',
  durationDays: 30,
  price: 100_000,
  compareAtPrice: null,
  quotaGib: 20,
  dailyQuotaGib: null,
  deviceLimit: 1,
  badgeFa: null,
  isFeatured: false,
  descriptionFa: null,
  ...over,
})

/**
 * A "20GB" product's three-month package carries 60GB. Shown only as "20GB,
 * three months" it read as 20GB to last the quarter.
 */
describe('volumeNote', () => {
  it('spells out the whole allowance of a three-month package', () => {
    expect(volumeNote(plan({ durationDays: 90, quotaGib: 60 }))).toBe(
      'ماهی ۲۰ گیگابایت × ۳ ماه = در مجموع ۶۰ گیگابایت',
    )
  })

  it('counts a year as twelve months of the same volume', () => {
    // The ladder stores int(20 * 365 / 30) = 243.
    expect(volumeNote(plan({ durationDays: 365, quotaGib: 243 }))).toBe(
      'ماهی ۲۰ گیگابایت × ۱۲ ماه = در مجموع ۲۴۳ گیگابایت',
    )
  })

  it('has nothing to add to a one-month or weekly package', () => {
    expect(volumeNote(plan({ durationDays: 30 }))).toBeNull()
    expect(volumeNote(plan({ durationDays: 7, quotaGib: 4 }))).toBeNull()
  })

  it('says nothing about unlimited or daily-limit packages', () => {
    expect(volumeNote(plan({ durationDays: 90, quotaGib: null, planType: 'unlimited' }))).toBeNull()
    expect(volumeNote(plan({ durationDays: 90, planType: 'duration', dailyQuotaGib: 5 }))).toBeNull()
  })
})

describe('terms', () => {
  it('orders a product’s packages shortest term first', () => {
    const plans = [plan({ planId: 'y', durationDays: 365 }), plan({ planId: 'm', durationDays: 30 })]
    expect(byTerm(plans).map((p) => p.planId)).toEqual(['m', 'y'])
  })

  it('does not count a weekly term in months', () => {
    expect(monthsIn(7)).toBeNull()
    expect(monthsIn(180)).toBe(6)
  })
})

describe('termsOf', () => {
  it('separates the terms with a comma, never a dot that reads as a Persian zero', () => {
    const product = {
      plans: [plan({ durationDays: 90 }), plan({ durationDays: 30 })],
    } as Parameters<typeof termsOf>[0]
    expect(termsOf(product)).toBe('۱ ماهه، ۳ ماهه')
  })
})
