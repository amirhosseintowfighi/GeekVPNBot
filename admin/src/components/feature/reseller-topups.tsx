'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Wallet } from 'lucide-react'

import { ApiError, api } from '@/lib/api'
import { faDate, faNumber, toman } from '@/lib/fa'
import type { PendingTopupRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'

/**
 * Resellers waiting to be able to sell.
 *
 * Above the reseller list, beside the applications, for the same reason: a
 * queue on a page nobody opens is a queue nobody answers - and this one has
 * somebody who has already sent money at the other end of it.
 *
 * It renders nothing when empty.
 */
export function ResellerTopups({ onDecided }: { onDecided: () => void }) {
  const { can } = useSession()
  const [busy, setBusy] = React.useState<string | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  const { data, mutate } = useSWR<PendingTopupRow[]>('reseller-topups', () =>
    api.pendingTopups(),
  )

  if (!can('resellers.read') || !data?.length) return null

  const decide = async (id: string, work: () => Promise<unknown>) => {
    setBusy(id)
    setError(null)
    try {
      await work()
      await mutate()
      onDecided()
    } catch (thrown) {
      setError(thrown instanceof ApiError ? thrown.messageFa : 'انجام نشد.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card className="border-primary/40 p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <Wallet className="size-4" />
        درخواست‌های شارژ نمایندگان
        <span className="text-muted-foreground">({faNumber(data.length)})</span>
      </div>
      {error ? <p className="mb-2 text-sm text-destructive">{error}</p> : null}
      <div className="space-y-2">
        {data.map((row) => (
          <div
            key={row.id}
            className="flex items-center justify-between gap-3 rounded-md border p-2 text-sm"
          >
            <div className="min-w-0">
              <div className="font-medium">
                {row.resellerNameFa} — {toman(row.amount)}
              </div>
              <div className="text-xs text-muted-foreground">
                {row.noteFa ?? 'بدون توضیح'} · {faDate(row.createdAt)}
              </div>
            </div>
            {can('resellers.write') ? (
              <div className="flex shrink-0 gap-2">
                <Button
                  size="sm"
                  disabled={busy === row.id}
                  onClick={() => void decide(row.id, () => api.approveTopup(row.id))}
                >
                  تأیید
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={busy === row.id}
                  onClick={() => void decide(row.id, () => api.rejectTopup(row.id, ''))}
                >
                  رد
                </Button>
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </Card>
  )
}
