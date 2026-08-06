/**
 * Persian formatting and bidirectional-text helpers.
 *
 * The TypeScript twin of presentation/bot/ui/fa.py. Every number a customer
 * sees goes through here, for two reasons:
 *
 * 1. Digits. Latin digits inside Persian copy look broken to a Persian reader.
 *    There is no CSS fix; the characters themselves have to change.
 * 2. Direction. An RTL paragraph containing a Latin-script run - a config URL,
 *    an email, a crypto address - has its punctuation reordered by the Unicode
 *    bidi algorithm unless the run is explicitly isolated. That is the bug
 *    which turns 1.2.3.4:443 into 443:1.2.3.4 on a real phone. `ltr()` wraps
 *    such runs in an isolate pair so it cannot happen.
 */

import { JALALI_MONTHS, WEEKDAYS, toJalali } from './jalali'

export const RLM = '\u200f'
export const LRM = '\u200e'
export const LRI = '\u2066'
export const RLI = '\u2067'
export const FSI = '\u2068'
export const PDI = '\u2069'
/** Persian half-space. Wrong spacing here is the clearest sign of a machine. */
export const ZWNJ = '\u200c'

export const PERSIAN_DIGITS = '\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9'
const ARABIC_DIGITS = '\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669'
/** Arabic thousands separator, correct for Persian typography. */
const THOUSANDS_SEP = '\u066c'
const DECIMAL_SEP = '\u066b'
export const PERCENT_SIGN = '\u066a'

const TOMAN = '\u062a\u0648\u0645\u0627\u0646'
const UNLIMITED = '\u0646\u0627\u0645\u062d\u062f\u0648\u062f'
const GIGABYTE = '\u06af\u06cc\u06af\u0627\u0628\u0627\u06cc\u062a'

/** Latin digits to Persian. */
export function faDigits(value: string | number): string {
  return String(value).replace(/[0-9]/g, (d) => PERSIAN_DIGITS[Number(d)] as string)
}

/** Persian or Arabic digits back to Latin, for parsing what the user typed. */
export function enDigits(value: string): string {
  return value.replace(/[\u06f0-\u06f9\u0660-\u0669]/g, (d) => {
    const persian = PERSIAN_DIGITS.indexOf(d)
    return String(persian >= 0 ? persian : ARABIC_DIGITS.indexOf(d))
  })
}

/**
 * Make free-form input parseable.
 *
 * Persian keyboards emit their own digits, and people paste amounts with
 * separators already in them. Both have to survive the trip to `Number()`.
 */
export function normalizeInput(value: string): string {
  return enDigits(value)
    .replace(/[\u066c,\s]/g, '')
    .replace(DECIMAL_SEP, '.')
    .trim()
}

/** Isolate a run so the surrounding RTL text cannot reorder it. */
export function isolate(value: string | number): string {
  return FSI + String(value) + PDI
}

/** Isolate a run and force it left-to-right. Use for URLs, addresses, IDs. */
export function ltr(value: string | number): string {
  return LRI + String(value) + PDI
}

export function faNumber(value: number, decimals = 0): string {
  const fixed = decimals > 0 ? value.toFixed(decimals) : String(Math.round(value))
  const parts = fixed.split('.')
  const whole = (parts[0] as string).replace(/\B(?=(\d{3})+(?!\d))/g, THOUSANDS_SEP)
  const joined = parts[1] ? whole + DECIMAL_SEP + parts[1] : whole
  return faDigits(joined)
}

export function toman(amount: number, withUnit = true): string {
  const formatted = faNumber(amount)
  return withUnit ? formatted + ' ' + TOMAN : formatted
}

export function percent(value: number): string {
  return faNumber(value) + PERCENT_SIGN
}

/** Volume. `null` means an unlimited package, which has no number to show. */
export function gib(value: number | null): string {
  if (value === null) return UNLIMITED
  const decimals = value < 10 && value % 1 !== 0 ? 1 : 0
  return faNumber(value, decimals) + ' ' + GIGABYTE
}

/**
 * Every date helper accepts either a Date or the ISO string the API returns.
 *
 * The alternative - parsing at each call site - means forty chances to forget,
 * and a forgotten parse renders "Invalid Date" next to a subscription expiry.
 * Coercing once here is the only place it can go wrong.
 */
export type DateInput = Date | string | number

export function toDate(value: DateInput): Date {
  return value instanceof Date ? value : new Date(value)
}

export function faDate(value: DateInput): string {
  const date = toDate(value)
  const jalali = toJalali(date)
  const month = JALALI_MONTHS[jalali[1] - 1] as string
  return faDigits(jalali[2]) + ' ' + month + ' ' + faDigits(jalali[0])
}

export function faDateTime(value: DateInput): string {
  const date = toDate(value)
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  return faDate(date) + ' \u0633\u0627\u0639\u062a ' + faDigits(hh + ':' + mm)
}

export function faWeekday(value: DateInput): string {
  return WEEKDAYS[toDate(value).getDay()] as string
}

export function pluralizeDays(days: number): string {
  return faDigits(days) + ' \u0631\u0648\u0632'
}

/**
 * A human duration. Months and years read better than large day counts:
 * "one year" is instantly legible where "365 days" needs a beat of arithmetic.
 */
export function faDuration(days: number): string {
  if (days >= 365 && days % 365 === 0) {
    return faDigits(days / 365) + ' \u0633\u0627\u0644\u0647'
  }
  if (days >= 30 && days % 30 === 0) {
    return faDigits(days / 30) + ' \u0645\u0627\u0647\u0647'
  }
  if (days >= 7 && days % 7 === 0) {
    return faDigits(days / 7) + ' \u0647\u0641\u062a\u0647'
  }
  return pluralizeDays(days)
}

/**
 * Relative time. Past and future are phrased differently, never signed.
 *
 * Accepts either a millisecond delta or an absolute timestamp, which is what
 * the screens actually hold. A bare number below the epoch threshold would be
 * ambiguous, so an absolute value is distinguished by being a Date or string.
 */
export function faRelative(value: DateInput | number): string {
  const deltaMs =
    typeof value === 'number' ? value : toDate(value).getTime() - Date.now()
  const past = deltaMs < 0
  const seconds = Math.abs(deltaMs) / 1000
  const render = (n: number, unit: string) =>
    faDigits(Math.floor(n)) +
    ' ' +
    unit +
    (past ? ' \u067e\u06cc\u0634' : ' \u062f\u06cc\u06af\u0631')

  if (seconds < 60) {
    return past
      ? '\u0647\u0645\u06cc\u0646 \u062d\u0627\u0644\u0627'
      : '\u062a\u0627 \u0644\u062d\u0638\u0627\u062a\u06cc \u062f\u06cc\u06af\u0631'
  }
  if (seconds < 3600) return render(seconds / 60, '\u062f\u0642\u06cc\u0642\u0647')
  if (seconds < 86400) return render(seconds / 3600, '\u0633\u0627\u0639\u062a')
  if (seconds < 2592000) return render(seconds / 86400, '\u0631\u0648\u0632')
  return render(seconds / 2592000, '\u0645\u0627\u0647')
}

/**
 * A countdown for flash sales and expiring subscriptions.
 *
 * Accepts a second count or a target timestamp. Never renders a negative: an
 * elapsed deadline shows zeros, not a growing negative clock.
 */
export function countdown(value: DateInput | number): string {
  const seconds =
    typeof value === 'number'
      ? value
      : (toDate(value).getTime() - Date.now()) / 1000
  const total = Math.max(0, Math.floor(seconds))
  const pad = (n: number) => String(n).padStart(2, '0')
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return faDigits(pad(h) + ':' + pad(m) + ':' + pad(s))
}

/** Clamp a usage ratio into [0, 1] so a bar can never overflow its track. */
export function usageFraction(used: number, total: number | null): number {
  if (total === null || total <= 0) return 0
  return Math.min(1, Math.max(0, used / total))
}

export function truncate(value: string, limit: number): string {
  if (value.length <= limit) return value
  return value.slice(0, Math.max(0, limit - 1)) + '\u2026'
}
