'use client'

import * as React from 'react'
import { useParams, useRouter } from 'next/navigation'
import useSWR from 'swr'
import { Minus, Plus } from 'lucide-react'

import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState } from '@/components/shell/states'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { SkeletonList } from '@/components/ui/skeleton'
import { api, ApiError, fetcher } from '@/lib/api'
import { faDigits, faDuration, gib, normalizeInput, toman } from '@/lib/fa'
import { anchorsByTerm, customFloor, totalGib } from '@/lib/plans'
import { haptic } from '@/lib/telegram'
import type { PlanCard, Storefront } from '@/lib/types'

/** Big enough for any real order; the backend refuses past it too. */
const MAX_GIB = 10_000

type TermPrice = { plan: PlanCard; total: number } | { plan: PlanCard; error: string }

/**
 * Any volume, priced off the shop's own packages.
 *
 * The customer types a monthly figure and sees every term priced for it at
 * once; the numbers are quotes from the backend, never arithmetic done here,
 * so what is shown is what checkout charges. Reached from the shop and from
 * renewal, which passes `renewOf` through to checkout.
 */
export default function CustomVolumePage() {
  const params = useParams<{ categoryId: string }>()
  const router = useRouter()
  const { data, error, mutate } = useSWR<Storefront>('/api/miniapp/storefront', fetcher)
  const category = data?.categories.find((c) => c.categoryId === params.categoryId)
  const floor = category ? customFloor(category) : null
  const anchors = React.useMemo(() => (category ? anchorsByTerm(category) : []), [category])

  const [renewOf, setRenewOf] = React.useState<string | undefined>(undefined)
  React.useEffect(() => {
    setRenewOf(new URLSearchParams(window.location.search).get('renewOf') ?? undefined)
  }, [])

  const [typed, setTyped] = React.useState('')
  React.useEffect(() => {
    if (floor !== null && typed === '') setTyped(String(floor))
  }, [floor, typed])
  const monthly = Number.parseInt(normalizeInput(typed), 10)
  const valid = Number.isFinite(monthly) && floor !== null && monthly >= floor && monthly <= MAX_GIB

  const [prices, setPrices] = React.useState<TermPrice[] | null>(null)
  React.useEffect(() => {
    if (!valid || anchors.length === 0) {
      setPrices(null)
      return
    }
    let cancelled = false
    // Debounced: every keystroke would otherwise be one quote per term.
    const timer = window.setTimeout(() => {
      void Promise.all(
        anchors.map((plan) =>
          api
            .quote(plan.planId, undefined, monthly)
            .then((quote): TermPrice => ({ plan, total: quote.total }))
            .catch(
              (err: unknown): TermPrice => ({
                plan,
                error: err instanceof ApiError ? err.messageFa : 'قیمت این مدت در دسترس نیست.',
              }),
            ),
        ),
      ).then((result) => {
        if (!cancelled) setPrices(result)
      })
    }, 350)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [valid, monthly, anchors])

  function step(delta: number) {
    haptic.select()
    const base = Number.isFinite(monthly) ? monthly : (floor ?? 0)
    setTyped(String(Math.min(MAX_GIB, Math.max(floor ?? 1, base + delta))))
  }

  function choose(plan: PlanCard) {
    haptic.impact('light')
    const query = new URLSearchParams({ custom: String(monthly) })
    if (renewOf) query.set('renewOf', renewOf)
    router.push(`/shop/${plan.planId}?${query.toString()}`)
  }

  return (
    <>
      <PageHeader title={'حجم دلخواه'} subtitle={category?.nameFa} />

      {error instanceof ApiError && !data ? (
        <ErrorState messageFa={error.messageFa} offline={error.status === 0} onRetry={() => void mutate()} />
      ) : !data ? (
        <SkeletonList count={3} />
      ) : !category || floor === null ? (
        <EmptyState
          title={'حجم دلخواه برای این سرویس نیست'}
          description={'از فروشگاه یکی از بسته‌ها را انتخاب کنید.'}
        />
      ) : (
        <div className="space-y-4 pb-6">
          <Card className="space-y-3 p-4">
            <label htmlFor="custom-gib" className="block text-sm font-bold">
              {'چند گیگ در ماه؟'}
            </label>
            <div className="flex items-center gap-2">
              <StepButton label={'کمتر'} onClick={() => step(-5)} disabled={!valid || monthly <= floor}>
                <Minus className="size-4" />
              </StepButton>
              <Input
                id="custom-gib"
                inputMode="numeric"
                ltr
                value={typed}
                onChange={(e) => setTyped(e.target.value.replace(/[^0-9۰-۹٠-٩]/g, ''))}
                className="nums text-center text-lg font-extrabold"
                aria-describedby="custom-gib-hint"
              />
              <StepButton label={'بیشتر'} onClick={() => step(5)} disabled={monthly >= MAX_GIB}>
                <Plus className="size-4" />
              </StepButton>
            </div>
            <p
              id="custom-gib-hint"
              className={[
                'nums text-xs leading-relaxed',
                valid || typed === '' ? 'text-muted-foreground' : 'text-destructive-ink',
              ].join(' ')}
            >
              {Number.isFinite(monthly) && monthly > MAX_GIB
                ? `بیشترین حجم ${gib(MAX_GIB)} در ماه است.`
                : `کمترین حجم ${gib(floor)} در ماه است. قیمت از روی بسته‌های همین سرویس حساب می‌شود.`}
            </p>
          </Card>

          {valid ? (
            <>
              <h2 className="section-label">{'مدت زمان را انتخاب کنید'}</h2>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {(prices ?? anchors.map((plan) => ({ plan, total: -1 }) as TermPrice)).map((row) => (
                  <TermRow
                    key={row.plan.planId}
                    row={row}
                    monthly={monthly}
                    onSelect={() => choose(row.plan)}
                  />
                ))}
              </div>
            </>
          ) : null}
        </div>
      )}
    </>
  )
}

function StepButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string
  onClick: () => void
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      className="flex size-[52px] shrink-0 items-center justify-center rounded-[14px] bg-input text-[color:var(--field-ink)] transition-colors hover:bg-[color:var(--hover)] disabled:opacity-40"
    >
      {children}
    </button>
  )
}

function TermRow({
  row,
  monthly,
  onSelect,
}: {
  row: TermPrice
  monthly: number
  onSelect: () => void
}) {
  const days = row.plan.durationDays
  const total = totalGib(monthly, days)
  const months = Math.round(days / 30)
  const loading = 'total' in row && row.total < 0
  const failed = 'error' in row
  return (
    <Card
      role="button"
      tabIndex={failed || loading ? -1 : 0}
      aria-disabled={failed || loading}
      onClick={failed || loading ? undefined : onSelect}
      onKeyDown={(event: React.KeyboardEvent) => {
        if (!failed && !loading && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault()
          onSelect()
        }
      }}
      className={[
        'flex items-center justify-between gap-3 p-4 transition-all',
        failed || loading ? 'opacity-60' : 'cursor-pointer active:scale-[0.99]',
      ].join(' ')}
    >
      <div className="min-w-0">
        <p className="text-[17px] font-extrabold">{faDuration(days)}</p>
        <p className="nums mt-0.5 text-xs text-muted-foreground">
          {months >= 2
            ? `ماهی ${gib(monthly)} × ${faDigits(months)} ماه = در مجموع ${gib(total)}`
            : `حجم ${gib(total)}`}
        </p>
      </div>
      <p className="nums shrink-0 text-sm font-extrabold">
        {failed ? row.error : loading ? '...' : toman(row.total)}
      </p>
    </Card>
  )
}
