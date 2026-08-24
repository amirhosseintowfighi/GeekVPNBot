/**
 * Which quota field a plan type is allowed to carry.
 *
 * Mirrors `Plan._validate_quotas` in domain/catalog/plan.py, which is strict in
 * both directions: a TRAFFIC package must carry a total volume and no daily
 * ceiling, a DURATION package a daily ceiling and no total, and an UNLIMITED
 * one neither. Sending the wrong field is not ignored - the package is
 * refused - and sending both is how a "10 GB" package silently becomes
 * "10 GB, but also 10 GB a day".
 */
export type PlanTypeValue = 'unlimited' | 'traffic' | 'duration'

export function quotaFieldsFor(
  planType: PlanTypeValue,
  gib: number,
): { monthlyQuotaGib?: number; dailyQuotaGib?: number } {
  if (planType === 'traffic') return { monthlyQuotaGib: gib }
  if (planType === 'duration') return { dailyQuotaGib: gib }
  return {}
}

export const PLAN_TYPE_LABEL_FA: Record<PlanTypeValue, string> = {
  unlimited: 'نامحدود',
  traffic: 'حجمی',
  duration: 'زمانی با سقف روزانه',
}

export const PLAN_TYPE_HINT_FA: Record<PlanTypeValue, string> = {
  unlimited: 'بدون سقف حجم. فقط مدت‌زمان می‌فروشید.',
  traffic: 'حجم کل بسته. با تمام شدن حجم یا رسیدن تاریخ، هرکدام زودتر، تمام می‌شود.',
  duration: 'سقف مصرف روزانه. برای مدت‌های بلند بدون ریسک اشباع سرور.',
}
