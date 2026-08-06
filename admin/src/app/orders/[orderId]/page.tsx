'use client'

import * as React from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import useSWR from 'swr'
import { ExternalLink, Receipt } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { faDateTime, faNumber, faRelative, toman } from '@/lib/fa'
import { PAYMENT_METHOD, PAYMENT_STATE, waitTone } from '@/lib/labels'
import type { OrderDetail } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader } from '@/components/shell/page-header'
import { ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, Textarea } from '@/components/ui/input'
import { SkeletonCards } from '@/components/ui/skeleton'

/** Canned rejection reasons. Free text is still allowed, but an operator
 *  clearing a queue at speed should not be inventing wording each time -
 *  inconsistent reasons are what generate the follow-up ticket. */
const REJECTION_PRESETS = [
  '\u0631\u0633\u06cc\u062f \u0646\u0627\u062e\u0648\u0627\u0646\u0627 \u0627\u0633\u062a',
  '\u0645\u0628\u0644\u063a \u0648\u0627\u0631\u06cc\u0632\u06cc \u0628\u0627 \u0645\u0628\u0644\u063a \u0633\u0641\u0627\u0631\u0634 \u0647\u0645\u062e\u0648\u0627\u0646\u06cc \u0646\u062f\u0627\u0631\u062f',
  '\u062a\u0631\u0627\u06a9\u0646\u0634 \u062f\u0631 \u062d\u0633\u0627\u0628 \u06cc\u0627\u0641\u062a \u0646\u0634\u062f',
  '\u0631\u0633\u06cc\u062f \u062a\u06a9\u0631\u0627\u0631\u06cc \u0627\u0633\u062a',
]

type ActionKind = 'approve' | 'reject' | 'refund' | null

/**
 * Order detail - where money actually moves.
 *
 * The safety rules on this screen, in order of importance:
 *
 * 1. Actions are only rendered when the order is in a state that permits
 *    them. An approved order shows no approve button; there is no path to
 *    double-provision a subscription from this UI.
 * 2. Every action goes through a confirmation dialog. `api` already sends an
 *    Idempotency-Key per mutation, and `Button loading` disables itself, so a
 *    double click cannot double-approve - but the dialog is what stops the
 *    wrong row being actioned in the first place.
 * 3. Rejection and refund require a reason. It is written to the audit log
 *    and shown to the customer, so "rejected, no explanation" is not a state
 *    this panel can produce.
 * 4. Permission checks hide destructive controls, but the server re-checks.
 *    `support` can approve; only `finance`, `admin` and `owner` can refund.
 */
export default function OrderDetailPage() {
  const params = useParams<{ orderId: string }>()
  const router = useRouter()
  const { can } = useSession()
  const orderId = params.orderId

  const [action, setAction] = React.useState<ActionKind>(null)
  const [reason, setReason] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [actionError, setActionError] = React.useState<string | null>(null)

  const { data, error, isLoading, mutate } = useSWR<OrderDetail>(
    ['order', orderId],
    () => api.order(orderId),
  )

  if (!can('orders.view')) return <ForbiddenState permission="orders.view" />

  const closeDialog = () => {
    setAction(null)
    setReason('')
    setActionError(null)
  }

  const runAction = async () => {
    if (!action) return
    setBusy(true)
    setActionError(null)
    try {
      if (action === 'approve') await api.approveOrder(orderId)
      if (action === 'reject') await api.rejectOrder(orderId, reason.trim())
      if (action === 'refund') await api.refundOrder(orderId, reason.trim())
      await mutate()
      closeDialog()
    } catch (thrown) {
      // The dialog stays open on failure. Closing it would leave the operator
      // unsure whether the money moved.
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

  const stateMeta = PAYMENT_STATE[data.state]
  const methodMeta = PAYMENT_METHOD[data.method]
  const pending = data.state === 'pending_review'
  const refundable = data.state === 'approved'
  const reasonRequired = action === 'reject' || action === 'refund'
  const reasonTooShort = reasonRequired && reason.trim().length < 5

  return (
    <>
      <PageHeader
        breadcrumb={[{ href: '/orders', labelFa: '\u0633\u0641\u0627\u0631\u0634\u200c\u0647\u0627' }]}
        title={'\u0633\u0641\u0627\u0631\u0634 ' + data.reference}
        description={faDateTime(data.createdAt)}
        actions={
          <div className="flex flex-wrap gap-2">
            {pending && can('orders.approve') ? (
              <Button variant="success" onClick={() => setAction('approve')}>
                {'\u062a\u0623\u06cc\u06cc\u062f \u0648 \u062a\u062d\u0648\u06cc\u0644'}
              </Button>
            ) : null}

            {pending && can('orders.reject') ? (
              <Button variant="outline" onClick={() => setAction('reject')}>
                {'\u0631\u062f \u067e\u0631\u062f\u0627\u062e\u062a'}
              </Button>
            ) : null}

            {refundable && can('orders.refund') ? (
              <Button variant="destructive" onClick={() => setAction('refund')}>
                {'\u0627\u0633\u062a\u0631\u062f\u0627\u062f \u0648\u062c\u0647'}
              </Button>
            ) : null}
          </div>
        }
      />

      <div className="grid gap-3 xl:grid-cols-3">
        {/* --- payment evidence: the reason this screen exists --- */}
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>{'\u0645\u062f\u0631\u06a9 \u067e\u0631\u062f\u0627\u062e\u062a'}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={stateMeta.tone} dot>
                {stateMeta.fa}
              </Badge>
              <Badge variant={methodMeta.tone}>{methodMeta.fa}</Badge>
              {pending ? (
                <Badge variant={waitTone(data.waitingMinutes)}>
                  {'\u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 ' +
                    faNumber(data.waitingMinutes) +
                    ' \u062f\u0642\u06cc\u0642\u0647'}
                </Badge>
              ) : null}
            </div>

            {data.method === 'card' && data.receiptUrl ? (
              <a
                href={data.receiptUrl}
                target="_blank"
                rel="noreferrer"
                className="block overflow-hidden rounded-md border border-border"
              >
                {/* Plain img: the receipt is a user upload on an unknown host,
                    so next/image optimisation is not worth the config. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={data.receiptUrl}
                  alt={'\u0631\u0633\u06cc\u062f \u067e\u0631\u062f\u0627\u062e\u062a'}
                  className="max-h-96 w-full bg-muted object-contain"
                />
              </a>
            ) : null}

            {data.method === 'card' && !data.receiptUrl ? (
              <p className="flex items-center gap-2 rounded-md bg-muted/50 px-3 py-2 text-2xs text-muted-foreground">
                <Receipt className="size-3.5" aria-hidden />
                {'\u0647\u0646\u0648\u0632 \u0631\u0633\u06cc\u062f\u06cc \u0622\u067e\u0644\u0648\u062f \u0646\u0634\u062f\u0647 \u0627\u0633\u062a.'}
              </p>
            ) : null}

            {data.method === 'crypto' ? (
              <dl className="space-y-2 text-2xs">
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-muted-foreground">{'\u0634\u0628\u06a9\u0647'}</dt>
                  <dd dir="ltr" className="font-mono">{data.cryptoNetwork ?? '\u2014'}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="shrink-0 text-muted-foreground">{'\u0622\u062f\u0631\u0633'}</dt>
                  <dd dir="ltr" className="truncate font-mono">{data.cryptoAddress ?? '\u2014'}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="shrink-0 text-muted-foreground">{'\u0634\u0646\u0627\u0633\u0647\u0654 \u062a\u0631\u0627\u06a9\u0646\u0634'}</dt>
                  <dd className="flex min-w-0 items-center gap-1">
                    <span dir="ltr" className="truncate font-mono">{data.txid ?? '\u2014'}</span>
                    {data.txid && data.cryptoNetwork ? (
                      <ExternalLink className="size-3 shrink-0 text-muted-foreground" aria-hidden />
                    ) : null}
                  </dd>
                </div>
              </dl>
            ) : null}

            {data.rejectionReasonFa ? (
              <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-2xs text-destructive">
                {'\u0639\u0644\u062a \u0631\u062f: ' + data.rejectionReasonFa}
              </p>
            ) : null}

            {data.reviewedByFa && data.reviewedAt ? (
              <p className="text-2xs text-muted-foreground">
                {'\u0628\u0631\u0631\u0633\u06cc \u062a\u0648\u0633\u0637 ' +
                  data.reviewedByFa +
                  '\u060c ' +
                  faRelative(data.reviewedAt)}
              </p>
            ) : null}
          </CardContent>
        </Card>

        {/* --- what was bought --- */}
        <Card>
          <CardHeader>
            <CardTitle>{'\u0627\u0642\u0644\u0627\u0645 \u0633\u0641\u0627\u0631\u0634'}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-2xs">
            <p>
              <Link href={'/users/' + data.userId} className="text-primary hover:underline">
                {data.userFa}
              </Link>
            </p>

            <div className="space-y-1.5 border-t border-border pt-2">
              {data.lines.map((line, index) => (
                <div key={index} className="flex items-start justify-between gap-2">
                  <span className="text-muted-foreground">{line.labelFa}</span>
                  {/* Discounts arrive negative and are shown in green: the
                      customer gained, and a red minus reads as a charge. */}
                  <span className={'nums ' + (line.amount < 0 ? 'text-success' : '')}>
                    {toman(line.amount, false)}
                  </span>
                </div>
              ))}
            </div>

            <div className="flex items-center justify-between border-t border-border pt-2 font-semibold">
              <span>{'\u0645\u0628\u0644\u063a \u067e\u0631\u062f\u0627\u062e\u062a\u06cc'}</span>
              <span className="nums">{toman(data.amount)}</span>
            </div>

            {data.subscriptionId ? (
              <Link
                href={'/users/' + data.userId}
                className="block pt-1 text-primary hover:underline"
              >
                {'\u0645\u0634\u0627\u0647\u062f\u0647\u0654 \u0627\u0634\u062a\u0631\u0627\u06a9 \u0633\u0627\u062e\u062a\u0647\u200c\u0634\u062f\u0647'}
              </Link>
            ) : null}
          </CardContent>
        </Card>
      </div>

      {/* --- confirmation --- */}
      <Dialog open={action !== null} onOpenChange={(open) => (open ? null : closeDialog())}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {action === 'approve'
                ? '\u062a\u0623\u06cc\u06cc\u062f \u067e\u0631\u062f\u0627\u062e\u062a'
                : action === 'reject'
                  ? '\u0631\u062f \u067e\u0631\u062f\u0627\u062e\u062a'
                  : '\u0627\u0633\u062a\u0631\u062f\u0627\u062f \u0648\u062c\u0647'}
            </DialogTitle>
            <DialogDescription>
              {action === 'approve'
                ? '\u0627\u0634\u062a\u0631\u0627\u06a9 \u0628\u0644\u0627\u0641\u0627\u0635\u0644\u0647 \u0633\u0627\u062e\u062a\u0647 \u0648 \u0628\u0647 \u06a9\u0627\u0631\u0628\u0631 \u0627\u0637\u0644\u0627\u0639 \u062f\u0627\u062f\u0647 \u0645\u06cc\u200c\u0634\u0648\u062f. \u0627\u06cc\u0646 \u0627\u0642\u062f\u0627\u0645 \u0628\u0631\u06af\u0634\u062a\u200c\u067e\u0630\u06cc\u0631 \u0646\u06cc\u0633\u062a.'
                : action === 'reject'
                  ? '\u0639\u0644\u062a \u0631\u062f \u0628\u0631\u0627\u06cc \u06a9\u0627\u0631\u0628\u0631 \u0627\u0631\u0633\u0627\u0644 \u0645\u06cc\u200c\u0634\u0648\u062f\u061b \u0648\u0627\u0636\u062d \u0628\u0646\u0648\u06cc\u0633\u06cc\u062f.'
                  : '\u0645\u0628\u0644\u063a \u0628\u0647 \u06a9\u06cc\u0641 \u067e\u0648\u0644 \u06a9\u0627\u0631\u0628\u0631 \u0628\u0627\u0632\u0645\u06cc\u200c\u06af\u0631\u062f\u062f \u0648 \u0627\u0634\u062a\u0631\u0627\u06a9 \u062a\u0639\u0644\u06cc\u0642 \u0645\u06cc\u200c\u0634\u0648\u062f.'}
            </DialogDescription>
          </DialogHeader>

          <DialogBody className="space-y-3">
            <div className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2 text-2xs">
              <span className="text-muted-foreground">{data.reference}</span>
              <span className="nums font-semibold">{toman(data.amount)}</span>
            </div>

            {reasonRequired ? (
              <>
                <div className="flex flex-wrap gap-1.5">
                  {REJECTION_PRESETS.map((preset) => (
                    <Button
                      key={preset}
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setReason(preset)}
                    >
                      {preset}
                    </Button>
                  ))}
                </div>

                <Field
                  label={'\u0639\u0644\u062a'}
                  hint={'\u062f\u0633\u062a\u200c\u06a9\u0645 \u06f5 \u062d\u0631\u0641'}
                  error={reason.length > 0 && reasonTooShort ? '\u0639\u0644\u062a \u062e\u06cc\u0644\u06cc \u06a9\u0648\u062a\u0627\u0647 \u0627\u0633\u062a' : undefined}
                >
                  <Textarea
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    rows={3}
                    autoFocus
                  />
                </Field>
              </>
            ) : null}

            {actionError ? (
              <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-2xs text-destructive">
                {actionError}
              </p>
            ) : null}
          </DialogBody>

          <DialogFooter>
            <Button variant="ghost" onClick={closeDialog} disabled={busy}>
              {'\u0627\u0646\u0635\u0631\u0627\u0641'}
            </Button>
            <Button
              variant={action === 'approve' ? 'success' : 'destructive'}
              loading={busy}
              disabled={reasonTooShort}
              onClick={runAction}
            >
              {'\u062a\u0623\u06cc\u06cc\u062f \u0646\u0647\u0627\u06cc\u06cc'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
