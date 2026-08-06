'use client'

import * as React from 'react'
import { useParams, useRouter } from 'next/navigation'
import useSWR from 'swr'

import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState, StaggerItem, StaggerList } from '@/components/shell/states'
import { PlanCard } from '@/components/feature/plan-card'
import { SkeletonList } from '@/components/ui/skeleton'
import { ApiError, fetcher } from '@/lib/api'
import type { Storefront } from '@/lib/types'

/**
 * Renewal.
 *
 * The backend returns renewal options as a storefront, filtered to what this
 * subscription can actually move to. That is why this screen reuses the shop
 * card verbatim instead of inventing a renewal-specific one - a renewal is a
 * purchase, and the price shown must go through the same quoting pipeline.
 *
 * Selecting a plan hands off to the ordinary checkout route. There is no
 * separate renewal checkout, so coupons, cashback disclosure and the payment
 * methods stay in one place.
 */
export default function RenewPage() {
  const params = useParams<{ subscriptionId: string }>()
  const router = useRouter()
  const subscriptionId = params.subscriptionId

  const { data, error, mutate } = useSWR<Storefront>(
    `/api/miniapp/subscriptions/${subscriptionId}/renewal-options`,
    fetcher,
  )

  const products = (data?.categories ?? []).flatMap((c) => c.products)
  const hasPlans = products.some((p) => p.plans.length > 0)

  return (
    <>
      <PageHeader
        title={'\u062a\u0645\u062f\u06cc\u062f \u0633\u0631\u0648\u06cc\u0633'}
        subtitle={'\u0628\u0633\u062a\u0647\u200c\u06cc \u062c\u062f\u06cc\u062f \u0631\u0627 \u0627\u0646\u062a\u062e\u0627\u0628 \u06a9\u0646\u06cc\u062f'}
      />

      {error instanceof ApiError && !data ? (
        <ErrorState
          messageFa={error.messageFa}
          offline={error.status === 0}
          onRetry={() => void mutate()}
        />
      ) : !data ? (
        <SkeletonList count={3} />
      ) : !hasPlans ? (
        <EmptyState
          title={'\u06af\u0632\u06cc\u0646\u0647\u200c\u06cc \u062a\u0645\u062f\u06cc\u062f\u06cc \u062f\u0631 \u062f\u0633\u062a\u0631\u0633 \u0646\u06cc\u0633\u062a'}
          description={'\u0628\u0627 \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc \u062f\u0631 \u062a\u0645\u0627\u0633 \u0628\u0627\u0634\u06cc\u062f \u062a\u0627 \u06af\u0632\u06cc\u0646\u0647\u200c\u06cc \u0645\u0646\u0627\u0633\u0628 \u0631\u0627 \u067e\u06cc\u062f\u0627 \u06a9\u0646\u06cc\u0645.'}
        />
      ) : (
        <div className="space-y-6 pb-4">
          {products.map((product) =>
            product.plans.length === 0 ? null : (
              <section key={product.productId} className="space-y-3">
                <h2 className="flex items-center gap-2 text-sm font-semibold">
                  {product.icon ? <span aria-hidden>{product.icon}</span> : null}
                  {product.nameFa}
                </h2>
                <StaggerList className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {product.plans.map((plan) => (
                    <StaggerItem key={plan.planId}>
                      <PlanCard
                        plan={plan}
                        onSelect={() => router.push(`/shop/${plan.planId}`)}
                      />
                    </StaggerItem>
                  ))}
                </StaggerList>
              </section>
            ),
          )}
        </div>
      )}
    </>
  )
}
