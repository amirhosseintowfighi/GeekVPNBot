/**
 * Gregorian to Jalali conversion.
 *
 * Deliberately dependency-free. Pulling a date library in for one function
 * would cost more bundle than the function itself, and - more importantly - a
 * second implementation could drift from the bot's. A customer must never see
 * one expiry date in the bot and a different one here, so this is a direct
 * port of the algorithm in presentation/bot/ui/fa.py.
 */

const GREGORIAN_MONTH_STARTS = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]

function isGregorianLeap(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0
}

/**
 * Returns `[year, month, day]` in the Jalali calendar.
 *
 * Line for line the algorithm in `presentation/bot/ui/fa.py`. What was here
 * before said the same thing in its comment and was a different algorithm
 * entirely - and a wrong one: it put Nowruz 1405 on 1404-12-30, so every date
 * in the Mini App was a day and sometimes a year out from the same date in the
 * bot. Its own test suite said so and had never been run.
 *
 * UTC getters throughout. The local-time ones made the answer depend on the
 * reader's timezone, which for anyone east of Tehran moved a subscription's
 * expiry to the previous day.
 */
export function toJalali(date: Date): [number, number, number] {
  const gy = date.getUTCFullYear()
  const gm = date.getUTCMonth() + 1
  const gd = date.getUTCDate()

  const gy2 = gy - 1600
  let gDayNo =
    365 * gy2 +
    Math.floor((gy2 + 3) / 4) -
    Math.floor((gy2 + 99) / 100) +
    Math.floor((gy2 + 399) / 400)
  gDayNo += (GREGORIAN_MONTH_STARTS[gm - 1] as number) + (gd - 1)
  if (gm > 2 && isGregorianLeap(gy)) gDayNo += 1

  let jDayNo = gDayNo - 79
  const jNp = Math.floor(jDayNo / 12053)
  jDayNo %= 12053

  let jy = 979 + 33 * jNp + 4 * Math.floor(jDayNo / 1461)
  jDayNo %= 1461

  if (jDayNo >= 366) {
    jy += Math.floor((jDayNo - 1) / 365)
    jDayNo = (jDayNo - 1) % 365
  }

  for (let i = 0; i < 11; i += 1) {
    const monthLength = i < 6 ? 31 : 30
    if (jDayNo < monthLength) return [jy, i + 1, jDayNo + 1]
    jDayNo -= monthLength
  }
  return [jy, 12, jDayNo + 1]
}

export const JALALI_MONTHS = [
  'فروردین',
  'اردیبهشت',
  'خرداد',
  'تیر',
  'مرداد',
  'شهریور',
  'مهر',
  'آبان',
  'آذر',
  'دی',
  'بهمن',
  'اسفند',
] as const

/** Indexed by `Date.getDay()`, where 0 is Sunday. */
export const WEEKDAYS = [
  'یکشنبه',
  'دوشنبه',
  'سه‌شنبه',
  'چهارشنبه',
  'پنجشنبه',
  'جمعه',
  'شنبه',
] as const
