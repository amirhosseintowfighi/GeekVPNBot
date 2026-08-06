/**
 * Gregorian to Jalali conversion.
 *
 * Deliberately dependency-free. Pulling a date library in for one function
 * would cost more bundle than the function itself, and - more importantly - a
 * second implementation could drift from the bot's. A customer must never see
 * one expiry date in the bot and a different one here, so this is a direct
 * port of the algorithm in presentation/bot/ui/fa.py.
 */

const BREAKS = [
  -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097,
  2192, 2262, 2324, 2394, 2456, 3178,
]

function jalaliCalendar(jalaliYear: number) {
  const gy = jalaliYear + 621
  let leapJ = -14
  let jp = BREAKS[0] as number
  let jump = 0

  for (let i = 1; i < BREAKS.length; i += 1) {
    const jm = BREAKS[i] as number
    jump = jm - jp
    if (jalaliYear < jm) break
    leapJ += Math.floor(jump / 33) * 8 + Math.floor((jump % 33) / 4)
    jp = jm
  }

  let n = jalaliYear - jp
  leapJ += Math.floor(n / 33) * 8 + Math.floor(((n % 33) + 3) / 4)
  if (jump % 33 === 4 && jump - n === 4) leapJ += 1

  const leapG =
    Math.floor(gy / 4) - Math.floor(((Math.floor(gy / 100) + 1) * 3) / 4) - 150
  const march = 20 + leapJ - leapG

  if (jump - n < 6) n = n - jump + Math.floor((jump + 4) / 33) * 33
  let leap = (((n + 1) % 33) - 1) % 4
  if (leap === -1) leap = 4

  return { leap, gy, march }
}

function toJulianDay(gy: number, gm: number, gd: number): number {
  let d =
    Math.floor(((gy + Math.floor((gm - 8) / 6) + 100100) * 1461) / 4) +
    Math.floor((153 * ((gm + 9) % 12) + 2) / 5) +
    gd -
    34840408
  d = d - Math.floor((Math.floor((gy + 100100 + Math.floor((gm - 8) / 6)) / 100) * 3) / 4) + 752
  return d
}

function fromJulianDay(jdn: number): [number, number, number] {
  let j = 4 * jdn + 139361631
  j += Math.floor((Math.floor((4 * jdn + 183187720) / 146097) * 3) / 4) * 4 - 3908
  const i = Math.floor((j % 1461) / 4) * 5 + 308
  const gd = Math.floor((i % 153) / 5) + 1
  const gm = (Math.floor(i / 153) % 12) + 1
  const gy = Math.floor(j / 1461) - 100100 + Math.floor((8 - gm) / 6)
  return [gy, gm, gd]
}

/** Returns `[year, month, day]` in the Jalali calendar. */
export function toJalali(date: Date): [number, number, number] {
  const jdn = toJulianDay(
    date.getFullYear(),
    date.getMonth() + 1,
    date.getDate(),
  )
  const gy = (fromJulianDay(jdn) as [number, number, number])[0]
  let jy = gy - 621
  const r = jalaliCalendar(jy)
  const firstDay = toJulianDay(r.gy, 3, r.march)
  let k = jdn - firstDay

  if (k >= 0) {
    if (k <= 185) return [jy, 1 + Math.floor(k / 31), (k % 31) + 1]
    k -= 186
  } else {
    jy -= 1
    k += 179
    if (r.leap === 1) k += 1
  }

  return [jy, 7 + Math.floor(k / 30), (k % 30) + 1]
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
