'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import { Bitcoin, CreditCard } from 'lucide-react'

import { PageHeader } from '@/components/shell/page-header'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { api, ApiError } from '@/lib/api'
import { enDigits, faNumber, normalizeInput, toman } from '@/lib/fa'
import { haptic } from '@/lib/telegram'

/**
 * Bounds and presets copied from the bot's wallet handler. They are duplicated
 * rather than fetched because they gate the *button*, not the transaction -
 * the backend enforces the real limits, and a client that guessed differently
 * would only ever be wrong in the direction of a confusing error.
 */
const MIN_TOPUP = 50_000
const MAX_TOPUP = 50_000_000
const PRESETS = [200_000, 500_000, 1_000_000, 2_000_000] as const

export default function TopupPage() {
  const router = useRouter()
  const [raw, setRaw] = React.useState('')
  const [method, setMethod] = React.useState<'card' | 'crypto'>('card')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  // Persian digits are accepted on input and normalised before parsing, so a
  // customer typing on a Persian keyboard is not told their number is invalid.
  const amount = Number.parseInt(enDigits(normalizeInput(raw)).replace(/\D/g, ''), 10)
  const valid = Number.isFinite(amount) && amount >= MIN_TOPUP && amount <= MAX_TOPUP

  async function submit() {
    if (!valid) return
    setBusy(true)
    setError(null)
    try {
      const details = await api.beginTopup(amount, method)
      if (!details.payment) throw new Error('top-up returned no payment')
      haptic.impact('medium')
      router.push(`/payments/${details.payment.paymentId}`)
    } catch (err) {
      haptic.notify('error')
      setError(
        err instanceof ApiError
          ? err.messageFa
          : '\u062b\u0628\u062a \u062f\u0631\u062e\u0648\u0627\u0633\u062a \u0645\u0645\u06a9\u0646 \u0646\u0634\u062f.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        title={'\u0627\u0641\u0632\u0627\u06cc\u0634 \u0645\u0648\u062c\u0648\u062f\u06cc'}
      />

      <div className="space-y-4 pb-6">
        <Card className="space-y-3 p-4">
          <label htmlFor="amount" className="text-sm font-medium">
            {'\u0645\u0628\u0644\u063a \u0645\u0648\u0631\u062f \u0646\u0638\u0631'}
          </label>

          <Input
            id="amount"
            inputMode="numeric"
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            placeholder={'\u0645\u062b\u0644\u0627\u064b \u06f5\u06f0\u06f0\u066c\u06f0\u06f0\u06f0'}
            className="nums text-lg"
          />

          {Number.isFinite(amount) && amount > 0 ? (
            <p className="nums text-xs text-muted-foreground">{toman(amount)}</p>
          ) : null}

          <div className="grid grid-cols-2 gap-2 pt-1">
            {PRESETS.map((preset) => (
              <Button
                key={preset}
                type="button"
                variant={amount === preset ? 'default' : 'outline'}
                size="sm"
                onClick={() => {
                  haptic.select()
                  setRaw(String(preset))
                }}
                className="nums"
              >
                {toman(preset, false)}
              </Button>
            ))}
          </div>

          <p className="nums text-[11px] leading-loose text-muted-foreground">
            {`\u062d\u062f\u0627\u0642\u0644 ${toman(MIN_TOPUP)} \u0648 \u062d\u062f\u0627\u06a9\u062b\u0631 ${toman(MAX_TOPUP)}`}
          </p>
        </Card>

        <Card className="space-y-2 p-4">
          <p className="text-sm font-medium">
            {'\u0631\u0648\u0634 \u067e\u0631\u062f\u0627\u062e\u062a'}
          </p>

          <div className="grid grid-cols-2 gap-2">
            <Button
              variant={method === 'card' ? 'default' : 'outline'}
              onClick={() => {
                haptic.select()
                setMethod('card')
              }}
            >
              <CreditCard className="size-4" aria-hidden />
              {'\u06a9\u0627\u0631\u062a \u0628\u0647 \u06a9\u0627\u0631\u062a'}
            </Button>
            <Button
              variant={method === 'crypto' ? 'default' : 'outline'}
              onClick={() => {
                haptic.select()
                setMethod('crypto')
              }}
            >
              <Bitcoin className="size-4" aria-hidden />
              {'\u0631\u0645\u0632\u0627\u0631\u0632'}
            </Button>
          </div>

          <p className="text-[11px] leading-loose text-muted-foreground">
            {'\u0647\u0631 \u062f\u0648 \u0631\u0648\u0634 \u067e\u0633 \u0627\u0632 \u0628\u0631\u0631\u0633\u06cc \u062f\u0633\u062a\u06cc \u0628\u0647 \u06a9\u06cc\u0641 \u067e\u0648\u0644 \u0627\u0636\u0627\u0641\u0647 \u0645\u06cc\u200c\u0634\u0648\u062f.'}
          </p>
        </Card>

        {error ? (
          <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs leading-loose text-destructive">
            {error}
          </p>
        ) : null}

        <Button full size="lg" loading={busy} disabled={!valid} onClick={() => void submit()}>
          {'\u0627\u062f\u0627\u0645\u0647'}
        </Button>
      </div>
    </>
  )
}
