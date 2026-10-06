'use client'

import * as React from 'react'
import useSWR from 'swr'

import { api, ApiError } from '@/lib/api'
import { faNumber, normalizeInput, toman } from '@/lib/fa'
import type { BroadcastAudience } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

/** The broadcast audiences that need no extra input. */
const AUDIENCES: Array<{ value: BroadcastAudience['segment']; labelFa: string }> = [
  { value: 'all', labelFa: 'همهٔ کاربران' },
  { value: 'active_subscribers', labelFa: 'دارای اشتراک فعال' },
  { value: 'no_service', labelFa: 'بدون سرویس فعال' },
  { value: 'never_purchased', labelFa: 'بدون خرید' },
  { value: 'expired', labelFa: 'منقضی‌شده' },
]

/**
 * Credit or debit every wallet in an audience at once.
 *
 * Two steps, like a broadcast: the audience is counted by the server first,
 * and the confirm button restates the count and the amount, because this
 * moves money in thousands of wallets and cannot be undone in one click.
 * A debit never takes a wallet below zero.
 */
export function BulkAdjustCard() {
  const [segment, setSegment] = React.useState<BroadcastAudience['segment']>('all')
  const [amount, setAmount] = React.useState('')
  const [direction, setDirection] = React.useState<'credit' | 'debit'>('credit')
  const [reason, setReason] = React.useState('')
  const [confirming, setConfirming] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const [message, setMessage] = React.useState<string | null>(null)

  const value = Number(normalizeInput(amount).replace(/[^\d]/g, '')) || 0
  const estimate = useSWR<{ count: number }>(['bulk-audience', segment], () =>
    api.estimateAudience({ segment }),
  )
  const valid = value > 0 && reason.trim().length >= 5

  const run = async () => {
    setBusy(true)
    setMessage(null)
    try {
      const result = await api.bulkAdjustWallets({
        signedAmount: direction === 'credit' ? value : -value,
        reasonFa: reason.trim(),
        segment,
      })
      setMessage(
        `${faNumber(result.adjusted)} کیف پول تغییر کرد` +
          (result.partial ? `، ${faNumber(result.partial)} کمتر از مبلغ` : '') +
          (result.skipped ? `، ${faNumber(result.skipped)} موجودی نداشتند` : ''),
      )
      setConfirming(false)
      setAmount('')
      setReason('')
    } catch (thrown) {
      setMessage(thrown instanceof ApiError ? thrown.messageFa : 'خطا')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>{'افزایش یا کاهش همگانی موجودی'}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2">
        <Field label={'مخاطب'}>
          <Select value={segment} onValueChange={(v) => setSegment(v as BroadcastAudience['segment'])}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {AUDIENCES.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.labelFa}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label={'نوع'}>
          <Select value={direction} onValueChange={(v) => setDirection(v as 'credit' | 'debit')}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="credit">{'افزایش'}</SelectItem>
              <SelectItem value="debit">{'کاهش'}</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field label={'مبلغ (تومان)'} hint={value ? toman(value) : undefined}>
          <Input ltr inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </Field>
        <Field label={'دلیل (در تاریخچهٔ کاربر دیده می‌شود)'}>
          <Input value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
          {confirming ? (
            <>
              <Button disabled={busy} onClick={run}>
                {`تأیید: ${direction === 'credit' ? 'افزایش' : 'کاهش'} ${toman(value)} برای ${faNumber(
                  estimate.data?.count ?? 0,
                )} کاربر`}
              </Button>
              <Button variant="ghost" disabled={busy} onClick={() => setConfirming(false)}>
                {'انصراف'}
              </Button>
            </>
          ) : (
            <Button disabled={!valid} onClick={() => setConfirming(true)}>
              {'ادامه'}
            </Button>
          )}
          {message ? <span className="text-2xs text-muted-foreground">{message}</span> : null}
        </div>
      </CardContent>
    </Card>
  )
}
