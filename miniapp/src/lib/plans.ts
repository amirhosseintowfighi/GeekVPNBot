import { faDigits, faDuration, gib, toman } from '@/lib/fa'
import type { PlanCard, ProductCard, Storefront } from '@/lib/types'

/**
 * Package arithmetic for the two-step shop: a volume first, then a term.
 *
 * A package's `quotaGib` is the whole term's allowance - the duration ladder
 * scales it with the months, so "20GB, three months" is 60GB on the panel.
 * Listed under a product called "20GB", that read as 20GB to last three
 * months, which undersold every long package.
 */

/** Whole months in a term, for terms long enough to be counted in months. */
export function monthsIn(days: number): number | null {
  // 45 days, not 30: a one-month package has nothing to multiply, and a weekly
  // one is not a fraction of a month anybody wants to read.
  if (days < 45) return null
  return Math.round(days / 30)
}

/**
 * "20GB a month x 3 months = 60GB in all", or null where it would say nothing:
 * a one-month or weekly term, an unlimited package, or a daily-limit one whose
 * allowance does not add up over the term.
 */
export function volumeNote(plan: Pick<PlanCard, 'planType' | 'quotaGib' | 'durationDays'>): string | null {
  if (plan.planType !== 'traffic' || plan.quotaGib === null) return null
  const months = monthsIn(plan.durationDays)
  if (months === null || months < 2) return null
  const monthly = Math.round(plan.quotaGib / months)
  return `ماهی ${gib(monthly)} × ${faDigits(months)} ماه = در مجموع ${gib(plan.quotaGib)}`
}

/**
 * The terms a product is sold in, shortest first: "۱ ماهه، ۳ ماهه، ۱ ساله".
 *
 * A Persian comma, not a middle dot: the Persian zero is itself a dot, so
 * "۱ ماهه · ۳ ماهه" read as "۱ ماهه ۰ ۳ ماهه".
 */
export function termsOf(product: ProductCard): string {
  const days = Array.from(new Set(product.plans.map((plan) => plan.durationDays))).sort(
    (a, b) => a - b,
  )
  return days.map(faDuration).join('\u060c ')
}

/** "From 120,000 toman", the bot's own line under a product. */
export function priceFrom(product: ProductCard): string | null {
  if (product.plans.length === 0) return null
  const cheapest = Math.min(...product.plans.map((plan) => plan.price))
  return `از ${toman(cheapest)}`
}

/** Shortest term first, so the page reads as a ladder, as in the bot. */
export function byTerm(plans: PlanCard[]): PlanCard[] {
  return [...plans].sort((a, b) => a.durationDays - b.durationDays || a.price - b.price)
}

export function findProduct(storefront: Storefront | undefined, productId: string): ProductCard | null {
  for (const category of storefront?.categories ?? []) {
    const found = category.products.find((product) => product.productId === productId)
    if (found) return found
  }
  return null
}
