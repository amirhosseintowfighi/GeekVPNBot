import { describe, expect, it } from 'vitest'

import {
  enDigits,
  faDigits,
  faNumber,
  gib,
  normalizeInput,
  percent,
  pluralizeDays,
  toman,
  truncate,
  usageFraction,
} from '@/lib/fa'

/**
 * These assertions are ported from the bot's `tests/unit/bot/test_fa.py`.
 *
 * The point is not to test the formatter twice - it is that the bot and the
 * Mini App must render the same number the same way. A customer who sees
 * "۵۸۰٬۰۰۰ تومان" in chat and "580000" here has been given two prices.
 */

describe('digit conversion', () => {
  it('converts ASCII digits to Persian', () => {
    expect(faDigits('1405')).toBe('\u06f1\u06f4\u06f0\u06f5')
  })

  it('round-trips back to ASCII', () => {
    expect(enDigits('\u06f1\u06f4\u06f0\u06f5')).toBe('1405')
  })

  it('leaves non-digits untouched', () => {
    expect(faDigits('GEEK-1405')).toBe('GEEK-\u06f1\u06f4\u06f0\u06f5')
  })

  it('normalises Arabic-Indic digits typed on some keyboards', () => {
    // Arabic-Indic (U+0660..) and Persian (U+06F0..) are different codepoints
    // that look nearly identical. A customer pasting a coupon from an Arabic
    // keyboard must not be told the code is invalid.
    expect(enDigits(normalizeInput('\u0661\u0662\u0663'))).toBe('123')
  })
})

describe('money', () => {
  it('groups thousands with the Persian separator', () => {
    expect(toman(580_000, false)).toBe('\u06f5\u06f8\u06f0\u066c\u06f0\u06f0\u06f0')
  })

  it('appends the unit by default', () => {
    expect(toman(580_000)).toContain('\u062a\u0648\u0645\u0627\u0646')
  })

  it('renders zero without a minus or an empty string', () => {
    expect(toman(0, false)).toBe('\u06f0')
  })

  it('formats the proven pricing values from the catalog tests', () => {
    // 680,000 less 15% is 578,000 in the domain's own rounding.
    expect(toman(578_000, false)).toBe(
      '\u06f5\u06f7\u06f8\u066c\u06f0\u06f0\u06f0',
    )
  })
})

describe('volume', () => {
  it('renders null as unlimited rather than zero', () => {
    // The single most dangerous formatting bug in this app: an unlimited plan
    // shown as "0 GB" reads as an exhausted one.
    expect(gib(null)).toBe('\u0646\u0627\u0645\u062d\u062f\u0648\u062f')
  })

  it('renders a numeric volume with a unit', () => {
    expect(gib(50)).toContain('\u06f5\u06f0')
  })
})

describe('usageFraction', () => {
  it('clamps above one so a bar can never overflow', () => {
    expect(usageFraction(120, 100)).toBe(1)
  })

  it('returns zero when the total is zero', () => {
    // Guards against a division by zero on a malformed plan.
    expect(usageFraction(5, 0)).toBe(0)
  })

  it('treats unlimited as zero usage', () => {
    expect(usageFraction(40, null)).toBe(0)
  })

  it('never returns a negative fraction', () => {
    expect(usageFraction(-5, 100)).toBe(0)
  })
})

describe('percent', () => {
  it('uses the Persian percent sign', () => {
    expect(percent(15)).toContain('\u066a')
  })
})

describe('pluralizeDays', () => {
  it('does not inflect the noun, matching Persian usage', () => {
    // Persian does not pluralise a counted noun. "۳۰ روز", never "۳۰ روزها".
    expect(pluralizeDays(30)).not.toContain('\u0647\u0627')
  })
})

describe('truncate', () => {
  it('leaves short strings alone', () => {
    expect(truncate('abc', 10)).toBe('abc')
  })

  it('never returns more characters than the limit', () => {
    expect(truncate('a'.repeat(50), 10).length).toBeLessThanOrEqual(10)
  })
})

describe('faNumber', () => {
  it('honours the decimals argument', () => {
    expect(faNumber(1.5, 1)).toContain('\u066b')
  })

  it('omits decimals by default', () => {
    expect(faNumber(1.5)).not.toContain('\u066b')
  })
})
