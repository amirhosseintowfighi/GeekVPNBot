import { describe, expect, it } from 'vitest'

import { quotaFieldsFor } from '@/lib/plans'

/**
 * Mirrors `Plan._validate_quotas` in domain/catalog/plan.py, which is strict in
 * both directions - the wrong field is refused outright, and both fields at
 * once turns "10 GB" into "10 GB, but also 10 GB a day".
 *
 * The ladder dialog used to hardcode `unlimited` and ask for no volume, so the
 * catalogue could only ever sell time.
 */
describe('quotaFieldsFor', () => {
  it('gives a traffic package a total volume and no daily ceiling', () => {
    expect(quotaFieldsFor('traffic', 50)).toEqual({ monthlyQuotaGib: 50 })
  })

  it('gives a duration package a daily ceiling and no total', () => {
    expect(quotaFieldsFor('duration', 3)).toEqual({ dailyQuotaGib: 3 })
  })

  it('gives an unlimited package neither', () => {
    expect(quotaFieldsFor('unlimited', 50)).toEqual({})
  })

  it('never sends both, whatever the type', () => {
    for (const planType of ['traffic', 'duration', 'unlimited'] as const) {
      const fields = quotaFieldsFor(planType, 10)
      expect(Object.keys(fields).length).toBeLessThanOrEqual(1)
    }
  })
})
