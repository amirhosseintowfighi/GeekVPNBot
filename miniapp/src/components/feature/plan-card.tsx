'use client'

import * as React from 'react'
import { Check, Infinity as InfinityIcon, Smartphone } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { faDuration, faNumber, gib, toman } from '@/lib/fa'
import { haptic } from '@/lib/telegram'
import type { PlanCard as PlanCardModel } from '@/lib/types'

/**
 * One purchasable package.
 *
 * The compare-at price is only rendered when the backend actually sent one.
 * The duration ladder deliberately omits it on the 30-day baseline and on the
 * weekly rung, and inventing a struck-through number here would undo that
 * honesty at the last mile.
 */
export function PlanCard({
  plan,
  onSelect,
  selected,
}: {
  plan: PlanCardModel
  onSelect?: (plan: PlanCardModel) => void
  selected?: boolean
}) {
  const hasDiscount =
    plan.compareAtPrice !== null && plan.compareAtPrice > plan.price

  const savingPercent = hasDiscount
    ? Math.round(
        ((plan.compareAtPrice! - plan.price) / plan.compareAtPrice!) * 100,
      )
    : 0

  const handleClick = () => {
    haptic.impact('light')
    onSelect?.(plan)
  }

  return (
    <Card
      role={onSelect ? 'button' : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onClick={onSelect ? handleClick : undefined}
      onKeyDown={
        onSelect
          ? (event: React.KeyboardEvent) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                handleClick()
              }
            }
          : undefined
      }
      className={cn(
        'relative flex flex-col gap-3 p-4 transition-all',
        onSelect && 'cursor-pointer active:scale-[0.99]',
        selected
          ? 'border-primary/70 ring-1 ring-primary/40'
          : 'hover:border-border',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{plan.nameFa}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {faDuration(plan.durationDays)}
          </p>
        </div>

        {plan.badgeFa ? (
          <Badge variant="brand" className="shrink-0">
            {plan.badgeFa}
          </Badge>
        ) : null}
      </div>

      <ul className="space-y-1.5 text-xs text-muted-foreground">
        <li className="flex items-center gap-2">
          {plan.planType === 'unlimited' ? (
            <InfinityIcon className="size-3.5 shrink-0 text-primary" aria-hidden />
          ) : (
            <Check className="size-3.5 shrink-0 text-primary" aria-hidden />
          )}
          <span>
            {plan.planType === 'duration' && plan.dailyQuotaGib !== null
              ? `\u0645\u0635\u0631\u0641 \u0631\u0648\u0632\u0627\u0646\u0647 \u062a\u0627 ${gib(plan.dailyQuotaGib)}`
              : `\u062d\u062c\u0645 ${gib(plan.quotaGib)}`}
          </span>
        </li>
        <li className="flex items-center gap-2">
          <Smartphone className="size-3.5 shrink-0 text-primary" aria-hidden />
          <span>
            {`${faNumber(plan.deviceLimit)} \u062f\u0633\u062a\u06af\u0627\u0647 \u0647\u0645\u0632\u0645\u0627\u0646`}
          </span>
        </li>
      </ul>

      <div className="mt-auto flex items-end justify-between gap-2 pt-1">
        <div className="min-w-0">
          {hasDiscount ? (
            <div className="flex items-center gap-2">
              <span className="nums text-xs text-muted-foreground line-through">
                {toman(plan.compareAtPrice!, false)}
              </span>
              <Badge variant="success" className="px-1.5 py-0 text-[10px]">
                {`${faNumber(savingPercent)}\u066a\u0640`}
              </Badge>
            </div>
          ) : null}
          <p className="nums text-base font-bold leading-tight">
            {toman(plan.price)}
          </p>
        </div>

        {selected ? (
          <span className="rounded-full bg-primary p-1 text-primary-foreground">
            <Check className="size-3.5" aria-hidden />
          </span>
        ) : null}
      </div>
    </Card>
  )
}
