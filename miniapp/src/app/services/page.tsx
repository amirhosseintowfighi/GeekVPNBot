'use client'

import * as React from 'react'
import Link from 'next/link'
import useSWR from 'swr'
import { ShoppingBag } from 'lucide-react'

import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState, StaggerItem, StaggerList } from '@/components/shell/states'
import { SubscriptionCardView } from '@/components/feature/subscription-card'
import { Button } from '@/components/ui/button'
import { SkeletonList } from '@/components/ui/skeleton'
import { api, ApiError, fetcher } from '@/lib/api'
import type { SubscriptionCard } from '@/lib/types'

/**
 * All of the customer's subscriptions.
 *
 * Link rotation is handled here rather than on a detail screen because it is
 * a one-tap action with a confirmation baked into its own result: the new URL
 * appears in place. Rotating invalidates the old link, so the mutation is
 * optimistic only in the sense that it revalidates immediately after.
 */
export default function ServicesPage() {
  const { data, error, mutate } = useSWR<SubscriptionCard[]>(
    '/api/miniapp/subscriptions',
    fetcher,
  )
  const [rotating, setRotating] = React.useState<string | null>(null)

  async function rotate(subscriptionId: string) {
    setRotating(subscriptionId)
    try {
      const updated = await api.rotateLink(subscriptionId)
      await mutate(
        (current) =>
          (current ?? []).map((sub) =>
            sub.subscriptionId === subscriptionId ? updated : sub,
          ),
        { revalidate: false },
      )
    } catch {
      // Revalidate rather than surface a toast: if rotation half-succeeded,
      // the server's copy is the one that matters and guessing here could
      // show a link that no longer works.
      void mutate()
    } finally {
      setRotating(null)
    }
  }

  return (
    <>
      <PageHeader
        title={'\u0633\u0631\u0648\u06cc\u0633\u200c\u0647\u0627\u06cc \u0645\u0646'}
        back={false}
      />

      {error instanceof ApiError && !data ? (
        <ErrorState
          messageFa={error.messageFa}
          offline={error.status === 0}
          onRetry={() => void mutate()}
        />
      ) : !data ? (
        <SkeletonList count={3} />
      ) : data.length === 0 ? (
        <EmptyState
          icon={ShoppingBag}
          title={'\u0647\u0646\u0648\u0632 \u0633\u0631\u0648\u06cc\u0633\u06cc \u0646\u062f\u0627\u0631\u06cc\u062f'}
          description={'\u0627\u0632 \u0641\u0631\u0648\u0634\u06af\u0627\u0647 \u06cc\u06a9 \u0628\u0633\u062a\u0647 \u0627\u0646\u062a\u062e\u0627\u0628 \u06a9\u0646\u06cc\u062f.'}
          action={
            <Button asChild size="sm">
              <Link href="/shop">
                {'\u0631\u0641\u062a\u0646 \u0628\u0647 \u0641\u0631\u0648\u0634\u06af\u0627\u0647'}
              </Link>
            </Button>
          }
        />
      ) : (
        <StaggerList className="space-y-3 pb-4">
          {data.map((sub) => (
            <StaggerItem key={sub.subscriptionId}>
              <SubscriptionCardView
                sub={sub}
                onRotate={(id) => void rotate(id)}
                rotating={rotating === sub.subscriptionId}
              />
            </StaggerItem>
          ))}
        </StaggerList>
      )}
    </>
  )
}
