import { describe, expect, it } from 'vitest'

import { usageTone } from '@/components/ui/progress'

/**
 * The usage bar's colour thresholds.
 *
 * These are not cosmetic. They are pinned to the same fractions the bot uses
 * to decide when to send a quota warning, so the bar turns amber in the app on
 * the same day the notification arrives in chat. If the two drift, a customer
 * gets a warning about a bar that still looks fine, or stares at a red bar
 * that never produced a warning.
 */
describe('usageTone', () => {
  it('is calm below three quarters', () => {
    expect(usageTone(0)).toBe('brand')
    expect(usageTone(0.5)).toBe('brand')
    expect(usageTone(0.749)).toBe('brand')
  })

  it('warns from exactly three quarters', () => {
    // Boundary asserted explicitly: 0.75 must already warn, not warn at 0.76.
    expect(usageTone(0.75)).toBe('warning')
    expect(usageTone(0.89)).toBe('warning')
  })

  it('escalates from exactly ninety percent', () => {
    expect(usageTone(0.9)).toBe('destructive')
    expect(usageTone(1)).toBe('destructive')
  })

  it('treats an over-full fraction as exhausted rather than wrapping', () => {
    expect(usageTone(1.4)).toBe('destructive')
  })
})
