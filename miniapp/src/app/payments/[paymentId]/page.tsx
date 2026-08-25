'use client'

import * as React from 'react'
import { useParams, useRouter } from 'next/navigation'
import useSWR from 'swr'
import { Check, Clock, Copy, Upload } from 'lucide-react'

import { PageHeader } from '@/components/shell/page-header'
import { ErrorState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { SkeletonCard } from '@/components/ui/skeleton'
import { api, ApiError, fetcher } from '@/lib/api'
import { faDateTime, normalizeInput, toman } from '@/lib/fa'
import { copyText, haptic } from '@/lib/telegram'
import type { PendingPayment } from '@/lib/types'

/** Matches the bot's `MIN_TXID`. Kept identical so the two never disagree. */
const MIN_TXID = 10

const STATE_META: Record<
  PendingPayment['state'],
  { labelFa: string; variant: 'success' | 'warning' | 'destructive' | 'muted' }
> = {
  draft: { labelFa: '\u067e\u06cc\u0634\u200c\u0646\u0648\u06cc\u0633', variant: 'muted' },
  awaiting_proof: {
    labelFa: '\u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 \u0631\u0633\u06cc\u062f',
    variant: 'warning',
  },
  pending_review: {
    labelFa: '\u062f\u0631 \u062d\u0627\u0644 \u0628\u0631\u0631\u0633\u06cc',
    variant: 'warning',
  },
  approved: { labelFa: '\u062a\u0623\u06cc\u06cc\u062f \u0634\u062f\u0647', variant: 'success' },
  rejected: { labelFa: '\u0631\u062f \u0634\u062f\u0647', variant: 'destructive' },
  expired: { labelFa: '\u0645\u0646\u0642\u0636\u06cc \u0634\u062f\u0647', variant: 'destructive' },
}

/**
 * A single payment: bank details or a crypto address, plus the proof step.
 *
 * This screen polls. Card-to-card and crypto both clear through a human, and
 * the customer sits here waiting; without polling they would have to pull to
 * refresh to discover something that already happened. Polling stops as soon
 * as the payment reaches a terminal state so an abandoned tab does not
 * hammer the API forever.
 */
export default function PaymentPage() {
  const params = useParams<{ paymentId: string }>()
  const router = useRouter()
  const paymentId = params.paymentId

  const { data, error, mutate } = useSWR<PendingPayment[]>(
    '/api/miniapp/payments/pending',
    fetcher,
    { refreshInterval: 15_000 },
  )

  const [payment, setPayment] = React.useState<PendingPayment | null>(null)
  const [txid, setTxid] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [formError, setFormError] = React.useState<string | null>(null)
  const [copied, setCopied] = React.useState<string | null>(null)

  const fromList = (data ?? []).find((p) => p.paymentId === paymentId) ?? null
  const current = payment ?? fromList

  const terminal =
    current?.state === 'approved' ||
    current?.state === 'rejected' ||
    current?.state === 'expired'

  // Once the reviewer approves, send the customer to the thing they bought
  // rather than leaving them on a receipt screen.
  React.useEffect(() => {
    if (current?.state === 'approved') {
      haptic.notify('success')
      const timer = window.setTimeout(() => router.replace('/services'), 1800)
      return () => window.clearTimeout(timer)
    }
    return undefined
  }, [current?.state, router])

  async function copy(value: string, key: string) {
    haptic.impact('light')
    await copyText(value)
    setCopied(key)
    window.setTimeout(() => setCopied(null), 1600)
  }

  async function submitTxid() {
    const value = normalizeInput(txid).trim()
    if (value.length < MIN_TXID) {
      setFormError(
        '\u0634\u0646\u0627\u0633\u0647 \u062a\u0631\u0627\u06a9\u0646\u0634 \u06a9\u0648\u062a\u0627\u0647 \u0627\u0633\u062a.',
      )
      return
    }
    setBusy(true)
    setFormError(null)
    try {
      const updated = await api.attachTxid(paymentId, value)
      setPayment(updated)
      haptic.notify('success')
      void mutate()
    } catch (err) {
      haptic.notify('error')
      setFormError(
        err instanceof ApiError
          ? err.messageFa
          : '\u062b\u0628\u062a \u0634\u0646\u0627\u0633\u0647 \u0645\u0645\u06a9\u0646 \u0646\u0634\u062f.',
      )
    } finally {
      setBusy(false)
    }
  }

  if (error instanceof ApiError && !data) {
    return (
      <>
        <PageHeader title={'\u067e\u0631\u062f\u0627\u062e\u062a'} />
        <ErrorState
          messageFa={error.messageFa}
          offline={error.status === 0}
          onRetry={() => void mutate()}
        />
      </>
    )
  }

  if (!current) {
    return (
      <>
        <PageHeader title={'\u067e\u0631\u062f\u0627\u062e\u062a'} />
        <SkeletonCard />
      </>
    )
  }

  const meta = STATE_META[current.state]

  return (
    <>
      <PageHeader
        title={'\u067e\u0631\u062f\u0627\u062e\u062a'}
        subtitle={`\u06a9\u062f \u067e\u06cc\u06af\u06cc\u0631\u06cc ${current.reference}`}
      />

      <div className="space-y-4 pb-6">
        <Card className="space-y-3 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs text-muted-foreground">
                {'\u0645\u0628\u0644\u063a'}
              </p>
              <p className="nums mt-0.5 text-xl font-bold">
                {toman(current.amount)}
              </p>
            </div>
            <Badge variant={meta.variant}>{meta.labelFa}</Badge>
          </div>
          <p className="nums text-xs text-muted-foreground">
            {faDateTime(current.createdAt)}
          </p>
        </Card>

        {/* Card-to-card */}
        {current.card ? (
          <Card className="space-y-3 p-4">
            <p className="text-sm font-medium">
              {'\u0627\u0646\u062a\u0642\u0627\u0644 \u06a9\u0627\u0631\u062a \u0628\u0647 \u06a9\u0627\u0631\u062a'}
            </p>

            <button
              type="button"
              onClick={() => void copy(current.card!.cardNumber, 'card')}
              className="flex w-full items-center justify-between gap-2 rounded-lg bg-secondary/50 px-3 py-3 transition-colors hover:bg-secondary"
            >
              <span className="nums font-mono text-base tracking-widest" dir="ltr">
                {current.card.cardNumber}
              </span>
              {copied === 'card' ? (
                <Check className="size-4 shrink-0 text-success" aria-hidden />
              ) : (
                <Copy className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              )}
            </button>

            <dl className="space-y-1.5 text-xs">
              <Row label={'\u0628\u0647 \u0646\u0627\u0645'} value={current.card.cardHolderFa} />
              <Row label={'\u0628\u0627\u0646\u06a9'} value={current.card.bankFa} />
            </dl>

            <Separator />

            <p className="flex items-start gap-2 text-xs leading-loose text-muted-foreground">
              <Clock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {current.card.reviewSlaFa}
            </p>

            {/*
              The receipt image is uploaded through the bot chat, not here.
              A Mini App cannot hand a file to Telegram's file storage without
              its own upload endpoint and virus scanning, and the bot already
              has a reviewed path for exactly this.

              What this button used to do was close the app and nothing else.
              The customer landed in the chat with no prompt and no state, sent
              the photo, and got "I did not understand that" - so the payment
              stayed unproven and they had no way to say so. The bot now
              attaches any photo to the payment that is waiting for one, and
              the only thing missing was telling them that before the app
              disappears.
            */}
            <p className="rounded-lg bg-secondary/40 px-3 py-2 text-xs leading-loose text-muted-foreground">
              {'\u067e\u0633 \u0627\u0632 \u0648\u0627\u0631\u06cc\u0632\u060c \u0639\u06a9\u0633 \u0631\u0633\u06cc\u062f \u0631\u0627 \u062f\u0631 \u0686\u062a \u0631\u0628\u0627\u062a \u0628\u0641\u0631\u0633\u062a\u06cc\u062f. \u062e\u0648\u062f\u06a9\u0627\u0631 \u0628\u0647 \u0647\u0645\u06cc\u0646 \u067e\u0631\u062f\u0627\u062e\u062a \u0648\u0635\u0644 \u0645\u06cc\u200c\u0634\u0648\u062f.'}
            </p>

            <Button
              variant="outline"
              full
              onClick={() => {
                haptic.impact('light')
                window.Telegram?.WebApp?.close?.()
              }}
            >
              <Upload className="size-4" aria-hidden />
              {'\u0628\u0627\u0632 \u06a9\u0631\u062f\u0646 \u0686\u062a \u0631\u0628\u0627\u062a'}
            </Button>
          </Card>
        ) : null}

        {/* Crypto */}
        {current.crypto ? (
          <Card className="space-y-3 p-4">
            <p className="text-sm font-medium">
              {'\u067e\u0631\u062f\u0627\u062e\u062a \u0628\u0627 \u0631\u0645\u0632\u0627\u0631\u0632'}
            </p>

            <dl className="space-y-1.5 text-xs">
              <Row label={'\u0634\u0628\u06a9\u0647'} value={current.crypto.network} ltr />
              <Row label={'\u0627\u0631\u0632'} value={current.crypto.asset} ltr />
              <Row
                label={'\u0645\u0642\u062f\u0627\u0631'}
                value={current.crypto.amountDisplay}
                ltr
              />
            </dl>

            <button
              type="button"
              onClick={() => void copy(current.crypto!.address, 'addr')}
              className="flex w-full items-center justify-between gap-2 rounded-lg bg-secondary/50 px-3 py-3 transition-colors hover:bg-secondary"
            >
              <span
                className="break-all text-start font-mono text-xs leading-relaxed"
                dir="ltr"
              >
                {current.crypto.address}
              </span>
              {copied === 'addr' ? (
                <Check className="size-4 shrink-0 text-success" aria-hidden />
              ) : (
                <Copy className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              )}
            </button>

            <p className="rounded-lg border border-warning/25 bg-warning/10 px-3 py-2 text-xs leading-loose text-warning">
              {'\u0641\u0642\u0637 \u0627\u0632 \u0647\u0645\u06cc\u0646 \u0634\u0628\u06a9\u0647 \u0627\u0633\u062a\u0641\u0627\u062f\u0647 \u06a9\u0646\u06cc\u062f. \u0627\u0631\u0633\u0627\u0644 \u0627\u0632 \u0634\u0628\u06a9\u0647\u200c\u06cc \u062f\u06cc\u06af\u0631 \u0642\u0627\u0628\u0644 \u0628\u0627\u0632\u06af\u0631\u062f\u0627\u0646\u062f\u0646 \u0646\u06cc\u0633\u062a.'}
            </p>

            {!terminal ? (
              <div className="space-y-2">
                <label className="text-xs text-muted-foreground" htmlFor="txid">
                  {'\u0634\u0646\u0627\u0633\u0647 \u062a\u0631\u0627\u06a9\u0646\u0634 (TxID)'}
                </label>
                <Input
                  id="txid"
                  ltr
                  value={txid}
                  onChange={(e) => setTxid(e.target.value)}
                  placeholder="0x..."
                  autoComplete="off"
                />
                <Button
                  full
                  loading={busy}
                  onClick={() => void submitTxid()}
                  disabled={!txid.trim()}
                >
                  {'\u062b\u0628\u062a \u0634\u0646\u0627\u0633\u0647'}
                </Button>
              </div>
            ) : null}
          </Card>
        ) : null}

        {formError ? (
          <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs leading-loose text-destructive">
            {formError}
          </p>
        ) : null}

        {current.state === 'pending_review' ? (
          <p className="text-center text-xs leading-loose text-muted-foreground">
            {'\u0627\u06cc\u0646 \u0635\u0641\u062d\u0647 \u062e\u0648\u062f\u0628\u0647\u200c\u062e\u0648\u062f \u0628\u0647\u200c\u0631\u0648\u0632 \u0645\u06cc\u200c\u0634\u0648\u062f. \u0644\u0627\u0632\u0645 \u0646\u06cc\u0633\u062a \u0645\u0646\u062a\u0638\u0631 \u0628\u0645\u0627\u0646\u06cc\u062f \u2014 \u0646\u062a\u06cc\u062c\u0647 \u0631\u0627 \u062f\u0631 \u0631\u0628\u0627\u062a \u0647\u0645 \u0627\u0637\u0644\u0627\u0639 \u0645\u06cc\u200c\u062f\u0647\u06cc\u0645.'}
          </p>
        ) : null}
      </div>
    </>
  )
}

function Row({
  label,
  value,
  ltr,
}: {
  label: string
  value: string
  ltr?: boolean
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="nums font-medium" dir={ltr ? 'ltr' : undefined}>
        {value}
      </dd>
    </div>
  )
}
