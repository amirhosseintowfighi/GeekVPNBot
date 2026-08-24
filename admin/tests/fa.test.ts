import { describe, expect, it } from 'vitest'

import { basisPoints } from '@/lib/fa'

describe('basisPoints', () => {
  it('converts the percentage an operator types into what the API stores', () => {
    // The bug this exists to prevent: the bulk coupon dialog sent 20 for
    // "20% off", which the API reads as basis points - a 0.2% discount that
    // looked like it worked and gave away nothing.
    expect(basisPoints(20)).toBe(2000)
    expect(basisPoints(100)).toBe(10_000)
    expect(basisPoints(1)).toBe(100)
  })

  it('rounds rather than leaving a fraction of a basis point', () => {
    expect(basisPoints(12.345)).toBe(1235)
  })
})
