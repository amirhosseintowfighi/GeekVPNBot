'use client'

import { useParams, useRouter } from 'next/navigation'
import useSWR from 'swr'

import { TermPicker } from '@/components/feature/term-picker'
import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState } from '@/components/shell/states'
import { SkeletonList } from '@/components/ui/skeleton'
import { ApiError, fetcher } from '@/lib/api'
import { findProduct } from '@/lib/plans'
import type { Storefront } from '@/lib/types'

/**
 * Renewal's second step. The checkout it hands off to carries `renewOf`, so
 * the purchase extends this service instead of adding a second one.
 */
export default function RenewTermsPage() {
  const params = useParams<{ subscriptionId: string; productId: string }>()
  const router = useRouter()
  const { data, error, mutate } = useSWR<Storefront>('/api/miniapp/storefront', fetcher)
  const product = findProduct(data, params.productId)

  return (
    <>
      <PageHeader
        title={'تمدید سرویس'}
        subtitle={product?.nameFa}
      />

      {error instanceof ApiError && !data ? (
        <ErrorState
          messageFa={error.messageFa}
          offline={error.status === 0}
          onRetry={() => void mutate()}
        />
      ) : !data ? (
        <SkeletonList count={3} />
      ) : !product || product.plans.length === 0 ? (
        <EmptyState
          title={'این بسته دیگر فروشی نیست'}
          description={'یک حجم دیگر انتخاب کنید.'}
        />
      ) : (
        <TermPicker
          product={product}
          onSelect={(plan) =>
            router.push(`/shop/${plan.planId}?renewOf=${params.subscriptionId}`)
          }
        />
      )}
    </>
  )
}
