'use client'

import { PlanCard } from '@/components/feature/plan-card'
import { StaggerItem, StaggerList } from '@/components/shell/states'
import { byTerm } from '@/lib/plans'
import type { PlanCard as PlanCardModel, ProductCard } from '@/lib/types'

/**
 * The second step: how long, once the volume is chosen. Shared by the shop
 * and by renewal, so the two cannot drift into different ways of choosing.
 */
export function TermPicker({
  product,
  onSelect,
}: {
  product: ProductCard
  onSelect: (plan: PlanCardModel) => void
}) {
  return (
    <div className="space-y-4 pb-4">
      {product.featuresFa.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5 px-1">
          {product.featuresFa.map((feature) => (
            <li
              key={feature}
              className="glass-clear inline-flex h-7 items-center rounded-[10px] px-2.5 text-xs font-medium"
            >
              {feature}
            </li>
          ))}
        </ul>
      ) : null}

      <h2 className="section-label">
        {'مدت زمان را انتخاب کنید'}
      </h2>

      <StaggerList className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {byTerm(product.plans).map((plan) => (
          <StaggerItem key={plan.planId}>
            <PlanCard plan={plan} onSelect={onSelect} />
          </StaggerItem>
        ))}
      </StaggerList>
    </div>
  )
}
