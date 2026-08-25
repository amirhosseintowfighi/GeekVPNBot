'use client'

import * as React from 'react'
import useSWR from 'swr'

import { api, ApiError } from '@/lib/api'
import { faDateTime, faNumber, toman } from '@/lib/fa'
import type { Paged, PaymentRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, Input, Textarea } from '@/components/ui/input'
import { SkeletonTable } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

/**
 * The card-to-card review queue.
 *
 * `GET /admin/payments` has existed since payments did - it defaults to
 * `pending_review` precisely because that is the queue - and no screen ever
 * called it. The panel had approve and reject buttons on the order detail and
 * no way to reach a payment that needed them, so a customer could transfer
 * money, send a receipt, and wait forever while the payment sat exactly where
 * it was designed to sit.
 *
 * Ordered by how long the customer has been waiting, because that is the only
 * thing on this screen that represents a person currently out of pocket.
 */
/**
 * The two states a payment can be stuck in, and what an operator can do about
 * each. `awaiting_proof` was invisible: the endpoint defaults to the review
 * queue and this screen never asked for anything else, so a customer who
 * started a card payment and never managed to send a receipt appeared nowhere
 * at all - not in the queue, not on any list, nothing to cancel or chase.
 */
const TABS = [
  { state: 'pending_review', labelFa: 'در انتظار بررسی' },
  { state: 'awaiting_proof', labelFa: 'در انتظار رسید' },
] as const

export default function PaymentsPage() {
  const { can } = useSession()
  const [acting, setActing] = React.useState<PaymentRow | null>(null)
  const [rejecting, setRejecting] = React.useState(false)
  const [tab, setTab] = React.useState<(typeof TABS)[number]['state']>('pending_review')

  const { data, error, isLoading, mutate } = useSWR<Paged<PaymentRow>>(
    ['payments-queue', tab],
    () => api.payments({ state: tab }),
    // A queue is worth re-reading when the operator comes back to the tab.
    { revalidateOnFocus: true, refreshInterval: 60_000 },
  )

  if (!can('payments.read')) return <ForbiddenState permission="payments.read" />

  const rows = data?.items ?? []

  return (
    <>
      <PageHeader
        title={'بررسی پرداخت‌ها'}
        description={'رسیدهای کارت‌به‌کارت در انتظار تأیید'}
        actions={
          <div className="flex gap-1 rounded-lg bg-secondary/50 p-1">
            {TABS.map((entry) => (
              <button
                key={entry.state}
                type="button"
                onClick={() => setTab(entry.state)}
                className={
                  'rounded-md px-3 py-1.5 text-2xs transition-colors ' +
                  (tab === entry.state
                    ? 'bg-background font-medium shadow-sm'
                    : 'text-muted-foreground hover:text-foreground')
                }
              >
                {entry.labelFa}
              </button>
            ))}
          </div>
        }
      />

      {error ? (
        <ErrorState
          messageFa={error instanceof ApiError ? error.messageFa : ''}
          offline={error instanceof ApiError && error.status === 0}
          onRetry={() => mutate()}
        />
      ) : null}

      <Card>
        {isLoading && !data ? (
          <SkeletonTable rows={5} cols={5} />
        ) : rows.length === 0 ? (
          <EmptyState
            title={'صف خالی است'}
            description={
              tab === 'pending_review'
                ? 'هر رسیدی که مشتری بفرستد همین‌جا می‌نشیند تا تأییدش کنید.'
                : 'پرداختی هست که مشتری هنوز رسیدش را نفرستاده باشد، اینجا دیده می‌شود.'
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{'شناسه'}</TableHead>
                <TableHead>{'مشتری'}</TableHead>
                <TableHead>{'مبلغ'}</TableHead>
                <TableHead>{'در انتظار'}</TableHead>
                <TableHead>{'رسید'}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((payment) => (
                <TableRow key={payment.id}>
                  <TableCell>
                    <span dir="ltr" className="font-mono text-2xs">
                      {payment.id.slice(0, 10)}
                    </span>
                  </TableCell>
                  <TableCell dir="ltr" className="font-mono text-2xs text-muted-foreground">
                    {payment.userId}
                  </TableCell>
                  <TableCell numeric className="font-semibold">
                    {toman(payment.amount, false)}
                  </TableCell>
                  <TableCell numeric>
                    {/* The column that decides the order of work. */}
                    <span
                      className={
                        (payment.waitingMinutes ?? 0) > 30 ? 'text-warning' : 'text-muted-foreground'
                      }
                    >
                      {faNumber(payment.waitingMinutes ?? 0) + ' دقیقه'}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {payment.proof ? (
                      <span className="text-2xs">
                        {faDateTime(payment.proof.submittedAt)}
                      </span>
                    ) : (
                      <Badge variant="muted">{'بدون رسید'}</Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {can('payments.approve') ? (
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          onClick={() => {
                            setRejecting(false)
                            setActing(payment)
                          }}
                        >
                          {'تأیید'}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => {
                            setRejecting(true)
                            setActing(payment)
                          }}
                        >
                          {'رد'}
                        </Button>
                      </div>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <ReviewDialog
        payment={acting}
        rejecting={rejecting}
        onClose={() => setActing(null)}
        onDone={() => mutate()}
      />
    </>
  )
}

/**
 * Approving is the step that takes the money and starts provisioning, and
 * rejecting is the one a customer reads. Both are deliberate and both ask for
 * something before they run: an amount that may differ from the invoice when
 * the customer transferred the wrong figure, or a reason in Persian.
 */
function ReviewDialog({
  payment,
  rejecting,
  onClose,
  onDone,
}: {
  payment: PaymentRow | null
  rejecting: boolean
  onClose: () => void
  onDone: () => void
}) {
  const [amount, setAmount] = React.useState('')
  const [reason, setReason] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [failure, setFailure] = React.useState<string | null>(null)

  React.useEffect(() => {
    setAmount(payment ? String(payment.amount) : '')
    setReason('')
    setFailure(null)
  }, [payment])

  const submit = async () => {
    if (!payment) return
    setBusy(true)
    setFailure(null)
    try {
      if (rejecting) {
        await api.rejectPayment(payment.id, reason.trim())
      } else {
        const typed = Number(amount.replace(/\D/g, '')) || 0
        // Only send an amount when it differs: the endpoint treats null as
        // "the invoice figure", and echoing it back invites a rounding drift.
        await api.approvePayment(payment.id, typed === payment.amount ? undefined : typed)
      }
      onDone()
      onClose()
    } catch (thrown) {
      setFailure(thrown instanceof ApiError ? thrown.messageFa : '')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={payment !== null} onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{rejecting ? 'رد پرداخت' : 'تأیید پرداخت'}</DialogTitle>
          <DialogDescription>
            {rejecting
              ? 'دلیل را مشتری در ربات می‌خواند. مشخص بنویسید.'
              : 'با تأیید، سفارش پرداخت‌شده می‌شود و ساخت اکانت آغاز می‌شود.'}
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-3">
          {/* The receipt itself. An operator has to read a reference number
              off it, so it is shown at a size worth reading and links out to
              the full image. */}
          {payment?.proof?.fileId ? (
            <a
              href={api.receiptUrl(payment.id)}
              target="_blank"
              rel="noreferrer"
              className="block overflow-hidden rounded-md border border-border"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={api.receiptUrl(payment.id)}
                alt={'رسید پرداخت'}
                className="max-h-72 w-full object-contain"
              />
            </a>
          ) : (
            <p className="rounded-md border border-border px-3 py-2 text-2xs text-muted-foreground">
              {'برای این پرداخت رسیدی ثبت نشده است.'}
            </p>
          )}

          {rejecting ? (
            <Field label={'دلیل رد'} hint={'برای مشتری فرستاده می‌شود'}>
              <Textarea
                rows={3}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                autoFocus
              />
            </Field>
          ) : (
            <Field
              label={'مبلغ واریزشده (تومان)'}
              hint={'اگر مشتری مبلغ دیگری واریز کرده، همان را وارد کنید'}
            >
              <Input
                ltr
                inputMode="numeric"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                autoFocus
              />
            </Field>
          )}

          {failure ? (
            <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-2xs text-destructive">
              {failure}
            </p>
          ) : null}
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {'انصراف'}
          </Button>
          <Button
            loading={busy}
            variant={rejecting ? 'destructive' : 'default'}
            disabled={rejecting && reason.trim().length < 3}
            onClick={submit}
          >
            {rejecting ? 'رد کن' : 'تأیید کن'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
