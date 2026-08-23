'use client'

import * as React from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import useSWR from 'swr'
import { RefreshCw } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { faDateTime, faNumber, toman } from '@/lib/fa'
import { ORDER_STATE } from '@/lib/labels'
import type { OrderDetail } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader } from '@/components/shell/page-header'
import { ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { SkeletonCards } from '@/components/ui/skeleton'

/**
 * One order.
 *
 * What this screen is *not*, any more: a payment review queue. It used to
 * offer approve, reject and refund against `/orders/{id}`, which has never
 * had any of those. Reviewing a card-to-card receipt is a payment operation -
 * `/api/v1/admin/payments/{paymentId}/approve|reject|refund` - keyed by
 * payment id, and a payment is not an order. It also rendered a receipt
 * image, a crypto txid and a rejection reason, none of which an order
 * carries. Every one of those controls posted to a URL that answered 404.
 *
 * What an order does have is a provisioning lifecycle, and exactly one
 * operator action: retry a provision that failed. That is this screen.
 */
export default function OrderDetailPage() {
  const params = useParams<{ orderId: string }>()
  const { can } = useSession()
  const orderId = params.orderId

  const [busy, setBusy] = React.useState(false)
  const [actionError, setActionError] = React.useState<string | null>(null)
  const [retryNote, setRetryNote] = React.useState<string | null>(null)

  const { data, error, isLoading, mutate } = useSWR<OrderDetail>(
    ['order', orderId],
    () => api.order(orderId),
  )

  if (!can('orders.read')) return <ForbiddenState permission="orders.read" />

  const retry = async () => {
    setBusy(true)
    setActionError(null)
    setRetryNote(null)
    try {
      const result = await api.retryProvision(orderId)
      setRetryNote(result.message ?? null)
      await mutate()
    } catch (thrown) {
      setActionError(thrown instanceof ApiError ? thrown.messageFa : '')
    } finally {
      setBusy(false)
    }
  }

  if (error) {
    return (
      <ErrorState
        messageFa={error instanceof ApiError ? error.messageFa : ''}
        offline={error instanceof ApiError && error.status === 0}
        onRetry={() => mutate()}
      />
    )
  }

  if (isLoading || !data) return <SkeletonCards count={3} />

  const stateMeta = ORDER_STATE[data.state]
  // Only a failed provision can be retried. Retrying a live one would hand the
  // customer a second account against a single payment. Gated on
  // orders.approve: retrying is the same authority as releasing the service.
  const retryable = data.state === 'failed' && can('payments.approve')

  return (
    <>
      <PageHeader
        breadcrumb={{ href: '/orders', labelFa: 'سفارش‌ها' }}
        title={'سفارش ' + data.number}
        description={faDateTime(data.placedAt)}
        actions={
          retryable ? (
            <Button size="sm" onClick={retry} disabled={busy}>
              <RefreshCw className="size-3.5" aria-hidden />
              {'تلاش دوباره برای تحویل'}
            </Button>
          ) : null
        }
      />

      {actionError ? <ErrorState messageFa={actionError} onRetry={retry} /> : null}

      {retryNote ? (
        <Card>
          <CardContent className="py-3 text-2xs text-muted-foreground">{retryNote}</CardContent>
        </Card>
      ) : null}

      <div className="grid gap-3 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{'وضعیت'}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-2xs">
            <Row labelFa={'وضعیت'}>
              <Badge variant={stateMeta.tone} dot>
                {stateMeta.fa}
              </Badge>
            </Row>
            <Row labelFa={'ثبت'}>{faDateTime(data.placedAt)}</Row>
            <Row labelFa={'پرداخت'}>{data.paidAt ? faDateTime(data.paidAt) : '—'}</Row>
            <Row labelFa={'تحویل'}>
              {data.provisionedAt ? faDateTime(data.provisionedAt) : '—'}
            </Row>
            {data.failureReason ? (
              <Row labelFa={'علت شکست'}>
                <span className="text-destructive">{data.failureReason}</span>
              </Row>
            ) : null}
            <Row labelFa={'کاربر'}>
              <Link href={'/users/' + data.userId} className="text-primary hover:underline">
                {faNumber(data.userId)}
              </Link>
            </Row>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{'پلن و مبلغ'}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-2xs">
            <Row labelFa={'پلن'}>{data.planNameFa}</Row>
            <Row labelFa={'مدت'}>{faNumber(data.durationDays) + ' روز'}</Row>
            <Row labelFa={'حجم'}>
              {data.trafficMib === null
                ? 'نامحدود'
                : faNumber(Math.round(data.trafficMib / 1024)) + ' گیگابایت'}
            </Row>
            <Row labelFa={'دستگاه'}>{faNumber(data.deviceLimit)}</Row>
            <Row labelFa={'تمدید'}>{data.isRenewal ? 'بله' : 'خیر'}</Row>

            <div className="my-2 border-t border-border" />

            <Row labelFa={'قیمت پایه'}>{toman(data.listPrice, false)}</Row>
            <Row labelFa={'تخفیف'}>
              <span className="text-warning">
                {data.discount > 0 ? toman(data.discount, false) : '—'}
              </span>
            </Row>
            {data.couponCode ? (
              <Row labelFa={'کد تخفیف'}>
                <span dir="ltr" className="font-mono">
                  {data.couponCode}
                </span>
              </Row>
            ) : null}
            <Row labelFa={'پرداختی'}>
              <span className="font-semibold">{toman(data.total)}</span>
            </Row>
          </CardContent>
        </Card>
      </div>
    </>
  )
}

function Row({ labelFa, children }: { labelFa: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{labelFa}</span>
      <span className="nums">{children}</span>
    </div>
  )
}
