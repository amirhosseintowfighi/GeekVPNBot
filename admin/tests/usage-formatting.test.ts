import { describe, expect, it } from 'vitest'

import { gib } from '@/lib/fa'

/**
 * Both subscription screens rounded usage to whole gigabytes by hand.
 *
 * That reported 3.44 GB as ۳ and everything under half a gigabyte as ۰ - and
 * ۰ is exactly what a usage figure that never synced looks like, so a display
 * bug and a broken sweep were indistinguishable from the panel.
 */
describe('how much traffic a customer has used', () => {
  it('does not round a real figure away to zero', () => {
    expect(gib(0.488)).not.toBe('۰ گیگابایت')
  })

  it('keeps a decimal on small amounts', () => {
    expect(gib(3.44)).toBe('۳٫۴ گیگابایت')
  })

  it('still says zero when it really is zero', () => {
    expect(gib(0)).toBe('۰ گیگابایت')
  })

  it('drops a pointless decimal on a whole number', () => {
    expect(gib(20)).toBe('۲۰ گیگابایت')
  })

  it('can leave the unit off, for "۳٫۴ از ۲۰ گیگابایت"', () => {
    expect(gib(3.44, false)).toBe('۳٫۴')
  })

  it('says unlimited rather than a number', () => {
    expect(gib(null)).not.toMatch(/\d/)
  })
})
