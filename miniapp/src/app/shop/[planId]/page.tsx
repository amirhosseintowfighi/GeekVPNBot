'use client'

import * as React from 'react'
import { useParams, useRouter } from 'next/navigation'
import useSWR from 'swr'
import { CreditCard, Bitcoin, Tag, Wallet as WalletIcon, X } from 'lucide-react'

import { PageHeader } from '@/components/shell/page-header'
import { ErrorState } from '@/components/shell/states'
import { PriceBreakdown } from '@/components/feature/price-breakdown'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { SkeletonCard } from '@/components/ui/skeleton'
import { api, ApiError, fetcher } from '@/lib/api'
import { faDuration, gib, normalizeInput, toman } from '@/lib/fa'
import { haptic } from '@/lib/telegram'
import type { Quote, Storefront, WalletSnapshot } from '@/lib/types'

type Method = 'wallet' | 'card' | 'crypto'

/**
 * Review and pay.
 *
 * The whole checkout is one screen with three decisions on it - coupon,
 * method, confirm - because every extra route between a customer and a
 * payment is somewhere to drop out. The heavier steps that follow (uploading
 * a receipt, pasting a txid) live on the payment screen, where they belong to
 * a payment that already exists.
 */
export default function CheckoutPage() {
  const params = useParams<{ planId: string }>()
  const router = useRouter()
  const planId = params.planId

  const storefront = useSWR<Storefront>('/api/miniapp/storefront', fetcher)
  const wallet = useSWR<WalletSnapshot>('/api/miniapp/wallet', fetcher)

  const [quote, setQuote] = React.useState<Quote | null>(null)
  const [quoteError, setQuoteError] = React.useState<string | null>(null)
  const [couponInput, setCouponInput] = React.useState('')
  const [appliedCoupon, setAppliedCoupon] = React.useState<string | null>(null)
  const [couponMessage, setCouponMessage] = React.useState<string | null>(null)
  const [couponPending, setCouponPending] = React.useState(false)
  const [method, setMethod] = React.useState<Method>('wallet')
  const [submitting, setSubmitting] = React.useState(false)
  const [submitError, setSubmitError] = React.useState<string | null>(null)

  const plan = React.useMemo(() => {
    for (const category of storefront.data?.categories ?? []) {
      for (const product of category.products) {
        const found = product.plans.find((p) => p.planId === planId)
        if (found) return found
      }
    }
    return null
  }, [storefront.data, planId])

  // Price the plan once the id is known, and again whenever a coupon is
  // applied or removed. The quote is authoritative - the card's own price is
  // a pre-discount display value and is never used to charge anyone.
  React.useEffect(() => {
    let cancelled = false
    setQuoteError(null)
    api
      .quote(planId, appliedCoupon ?? undefined)
      .then((result) => {
        if (!cancelled) setQuote(result)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setQuoteError(
          err instanceof ApiError
            ? err.messageFa
            : '\u0645\u062d\u0627\u0633\u0628\u0647 \u0642\u06cc\u0645\u062a \u0645\u0645\u06a9\u0646 \u0646\u0634\u062f.',
        )
      })
    return () => {
      cancelled = true
    }
  }, [planId, appliedCoupon])

  const balance = wallet.data?.balance ?? 0
  const total = quote?.total ?? 0
  const walletCovers = balance >= total

  // If the wallet cannot cover the order, silently pre-selecting it would
  // hand the customer a disabled confirm button with no explanation.
  React.useEffect(() => {
    if (quote && !walletCovers && method === 'wallet') setMethod('card')
  }, [quote, walletCovers, method])

  async function applyCoupon() {
    const code = normalizeInput(couponInput).trim().toUpperCase()
    if (!code) return
    setCouponPending(true)
    setCouponMessage(null)
    try {
      // previewCoupon never throws for a bad code - it answers. A rejected
      // coupon is an ordinary outcome and must not clear the screen.
      const preview = await api.previewCoupon(planId, code)
      setCouponMessage(preview.messageFa)
      if (preview.accepted) {
        haptic.notify('success')
        setAppliedCoupon(code)
        if (preview.quote) setQuote(preview.quote)
      } else {
        haptic.notify('error')
      }
    } catch (err) {
      setCouponMessage(
        err instanceof ApiError
          ? err.messageFa
          : '\u0628\u0631\u0631\u0633\u06cc \u06a9\u062f \u0645\u0645\u06a9\u0646 \u0646\u0634\u062f.',
      )
    } finally {
      setCouponPending(false)
    }
  }

  function clearCoupon() {
    setAppliedCoupon(null)
    setCouponInput('')
    setCouponMessage(null)
  }

  async function confirm() {
    setSubmitting(true)
    setSubmitError(null)
    try {
      const coupon = appliedCoupon ?? undefined
      if (method === 'wallet') {
        await api.payFromWallet(planId, coupon)
        haptic.notify('success')
        router.replace('/services?purchased=1')
        return
      }
      const details =
        method === 'card'
          ? await api.beginCardPayment(planId, coupon)
          : await api.beginCryptoPayment(planId, coupon)
      if (!details.payment) throw new Error('checkout returned no payment')
      haptic.impact('medium')
      router.push(`/payments/${details.payment.paymentId}`)
    } catch (err) {
      haptic.notify('error')
      setSubmitError(
        err instanceof ApiError
          ? err.messageFa
          : '\u062b\u0628\u062a \u0633\u0641\u0627\u0631\u0634 \u0645\u0645\u06a9\u0646 \u0646\u0634\u062f.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  if (quoteError && !quote) {
    return (
      <>
        <PageHeader title={'\u0628\u0631\u0631\u0633\u06cc \u0633\u0641\u0627\u0631\u0634'} />
        <ErrorState messageFa={quoteError} onRetry={() => setAppliedCoupon(appliedCoupon)} />
      </>
    )
  }

  return (
    <>
      <PageHeader
        title={'\u0628\u0631\u0631\u0633\u06cc \u0633\u0641\u0627\u0631\u0634'}
        subtitle={plan?.nameFa}
      />

      <div className="space-y-4 pb-28">
        {/* What is being bought */}
        {plan ? (
          <Card className="space-y-2 p-4">
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm font-semibold">{plan.nameFa}</p>
              {plan.badgeFa ? (
                <Badge variant="brand">{plan.badgeFa}</Badge>
              ) : null}
            </div>
            <p className="text-xs leading-loose text-muted-foreground">
              {[
                faDuration(plan.durationDays),
                plan.planType === 'duration' && plan.dailyQuotaGib !== null
                  ? `\u0631\u0648\u0632\u0627\u0646\u0647 \u062a\u0627 ${gib(plan.dailyQuotaGib)}`
                  : `\u062d\u062c\u0645 ${gib(plan.quotaGib)}`,
              ].join(' \u00b7 ')}
            </p>
          </Card>
        ) : (
          <SkeletonCard />
        )}

        {/* Coupon */}
        <Card className="space-y-3 p-4">
          <p className="flex items-center gap-2 text-sm font-medium">
            <Tag className="size-4 text-primary" aria-hidden />
            {'\u06a9\u062f \u062a\u062e\u0641\u06cc\u0641'}
          </p>

          {appliedCoupon ? (
            <div className="flex items-center justify-between gap-2 rounded-lg border border-success/25 bg-success/10 px-3 py-2">
              <span className="nums text-sm text-success" dir="ltr">
                {appliedCoupon}
              </span>
              <button
                type="button"
                onClick={clearCoupon}
                aria-label={'\u062d\u0630\u0641 \u06a9\u062f \u062a\u062e\u0641\u06cc\u0641'}
                className="rounded-full p-1 text-success hover:bg-success/20"
              >
                <X className="size-3.5" aria-hidden />
              </button>
            </div>
          ) : (
            <div className="flex gap-2">
              <Input
                ltr
                value={couponInput}
                onChange={(e) => setCouponInput(e.target.value)}
                placeholder="GEEK1405"
                autoComplete="off"
                autoCapitalize="characters"
              />
              <Button
                variant="outline"
                loading={couponPending}
                onClick={() => void applyCoupon()}
                disabled={!couponInput.trim()}
              >
                {'\u0627\u0639\u0645\u0627\u0644'}
              </Button>
            </div>
          )}

          {couponMessage ? (
            <p className="text-xs leading-relaxed text-muted-foreground">
              {couponMessage}
            </p>
          ) : null}
        </Card>

        {/* Price */}
        <Card className="p-4">
          {quote ? <PriceBreakdown quote={quote} /> : <SkeletonCard />}
        </Card>

        {/* Method */}
        <Card className="space-y-2 p-4">
          <p className="text-sm font-medium">
            {'\u0631\u0648\u0634 \u067e\u0631\u062f\u0627\u062e\u062a'}
          </p>

          <MethodOption
            selected={method === 'wallet'}
            disabled={!walletCovers}
            onSelect={() => setMethod('wallet')}
            icon={WalletIcon}
            title={'\u06a9\u06cc\u0641 \u067e\u0648\u0644'}
            note={
              walletCovers
                ? `\u0645\u0648\u062c\u0648\u062f\u06cc: ${toman(balance)} \u00b7 \u0641\u0648\u0631\u06cc`
                : `\u0645\u0648\u062c\u0648\u062f\u06cc \u06a9\u0627\u0641\u06cc \u0646\u06cc\u0633\u062a (${toman(balance)})`
            }
          />
          <MethodOption
            selected={method === 'card'}
            onSelect={() => setMethod('card')}
            icon={CreditCard}
            title={'\u06a9\u0627\u0631\u062a \u0628\u0647 \u06a9\u0627\u0631\u062a'}
            note={'\u067e\u0633 \u0627\u0632 \u0627\u0631\u0633\u0627\u0644 \u0631\u0633\u06cc\u062f\u060c \u062a\u0648\u0633\u0637 \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc \u0628\u0631\u0631\u0633\u06cc \u0645\u06cc\u200c\u0634\u0648\u062f'}
          />
          <MethodOption
            selected={method === 'crypto'}
            onSelect={() => setMethod('crypto')}
            icon={Bitcoin}
            title={'\u067e\u0631\u062f\u0627\u062e\u062a \u0628\u0627 \u0631\u0645\u0632\u0627\u0631\u0632'}
            note={'\u067e\u0633 \u0627\u0632 \u062b\u0628\u062a \u0634\u0646\u0627\u0633\u0647 \u062a\u0631\u0627\u06a9\u0646\u0634\u060c \u0628\u0631\u0631\u0633\u06cc \u0645\u06cc\u200c\u0634\u0648\u062f'}
          />

          <p className="pt-1 text-[11px] leading-loose text-muted-foreground">
            {'\u062f\u0631\u06af\u0627\u0647 \u0628\u0627\u0646\u06a9\u06cc \u0628\u0647\u200c\u0632\u0648\u062f\u06cc \u0627\u0636\u0627\u0641\u0647 \u0645\u06cc\u200c\u0634\u0648\u062f.'}
          </p>
        </Card>

        {submitError ? (
          <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs leading-loose text-destructive">
            {submitError}
          </p>
        ) : null}
      </div>

      {/* Sticky confirm. The amount is repeated on the button so nobody has to
          scroll back up to check what they are about to pay. */}
      <div className="safe-bottom fixed inset-x-0 bottom-16 z-30 mx-auto w-full max-w-2xl border-t border-border/70 bg-background/90 px-4 py-3 backdrop-blur-xl">
        <Button
          full
          size="lg"
          loading={submitting}
          disabled={!quote}
          onClick={() => void confirm()}
        >
          {quote
            ? `\u067e\u0631\u062f\u0627\u062e\u062a ${toman(quote.total)}`
            : '\u062f\u0631 \u062d\u0627\u0644 \u0645\u062d\u0627\u0633\u0628\u0647...'}
        </Button>
      </div>
    </>
  )
}

function MethodOption({
  selected,
  disabled,
  onSelect,
  icon: Icon,
  title,
  note,
}: {
  selected: boolean
  disabled?: boolean
  onSelect: () => void
  icon: React.ComponentType<{ className?: string }>
  title: string
  note: string
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => {
        haptic.select()
        onSelect()
      }}
      className={[
        'flex w-full items-start gap-3 rounded-lg border px-3 py-3 text-start transition-colors',
        selected
          ? 'border-primary/60 bg-primary/10'
          : 'border-border/70 hover:bg-secondary/40',
        disabled ? 'cursor-not-allowed opacity-50' : '',
      ].join(' ')}
    >
      <Icon className="mt-0.5 size-4 shrink-0 text-primary" />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium">{title}</span>
        <span className="nums mt-0.5 block text-xs leading-relaxed text-muted-foreground">
          {note}
        </span>
      </span>
      <span
        aria-hidden
        className={[
          'mt-1 size-4 shrink-0 rounded-full border-2 transition-colors',
          selected ? 'border-primary bg-primary' : 'border-muted-foreground/40',
        ].join(' ')}
      />
    </button>
  )
}
