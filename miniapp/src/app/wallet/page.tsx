'use client'

import * as React from 'react'
import Link from 'next/link'
import useSWR from 'swr'
import {
  ArrowDownLeft,
  ArrowUpRight,
  Gift,
  Plus,
  Receipt,
  Users,
} from 'lucide-react'

import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { SkeletonCard, SkeletonList } from '@/components/ui/skeleton'
import { ApiError, fetcher } from '@/lib/api'
import { faDateTime, faNumber, toman } from '@/lib/fa'
import type {
  TransactionKind,
  WalletSnapshot,
  WalletTransaction,
} from '@/lib/types'

/** Mirrors the bot's page size so the two paginate identically. */
const PAGE_SIZE = 10

const KIND_META: Record<
  TransactionKind,
  { labelFa: string; icon: React.ComponentType<{ className?: string }> }
> = {
  topup: { labelFa: '\u0634\u0627\u0631\u0698 \u06a9\u06cc\u0641 \u067e\u0648\u0644', icon: Plus },
  purchase: { labelFa: '\u062e\u0631\u06cc\u062f \u0628\u0633\u062a\u0647', icon: Receipt },
  cashback: { labelFa: '\u0628\u0627\u0632\u06af\u0634\u062a \u0648\u062c\u0647', icon: Gift },
  referral: { labelFa: '\u067e\u0627\u062f\u0627\u0634 \u0645\u0639\u0631\u0641\u06cc', icon: Users },
  refund: { labelFa: '\u0639\u0648\u062f\u062a \u0648\u062c\u0647', icon: ArrowDownLeft },
  adjustment: { labelFa: '\u0627\u0635\u0644\u0627\u062d \u062f\u0633\u062a\u06cc', icon: ArrowUpRight },
}

/** Mirrors `WalletTransaction.is_credit`. */
function isCredit(kind: TransactionKind): boolean {
  return (
    kind === 'topup' ||
    kind === 'cashback' ||
    kind === 'referral' ||
    kind === 'refund'
  )
}

export default function WalletPage() {
  const [page, setPage] = React.useState(1)

  const wallet = useSWR<WalletSnapshot>('/api/miniapp/wallet', fetcher)
  const history = useSWR<{ items: WalletTransaction[]; total: number }>(
    `/api/miniapp/wallet/transactions?page=${page}&page_size=${PAGE_SIZE}`,
    fetcher,
    // Keeping the previous page on screen while the next one loads stops the
    // list from collapsing to a spinner on every tap.
    { keepPreviousData: true },
  )

  const total = history.data?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <>
      <PageHeader title={'\u06a9\u06cc\u0641 \u067e\u0648\u0644'} back={false} />

      <div className="space-y-4 pb-4">
        {wallet.error instanceof ApiError && !wallet.data ? (
          <ErrorState
            messageFa={wallet.error.messageFa}
            offline={wallet.error.status === 0}
            onRetry={() => void wallet.mutate()}
          />
        ) : !wallet.data ? (
          <SkeletonCard />
        ) : (
          <Card glow className="space-y-4 p-5">
            <div>
              <p className="text-xs text-muted-foreground">
                {'\u0645\u0648\u062c\u0648\u062f\u06cc \u0642\u0627\u0628\u0644 \u0627\u0633\u062a\u0641\u0627\u062f\u0647'}
              </p>
              <p className="nums mt-1 text-3xl font-bold">
                {toman(wallet.data.balance)}
              </p>
            </div>

            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>
                {'\u0645\u062c\u0645\u0648\u0639 \u062e\u0631\u06cc\u062f'}
              </span>
              <span className="nums">{toman(wallet.data.lifetimeSpend)}</span>
            </div>

            <Button full asChild>
              <Link href="/wallet/topup">
                <Plus className="size-4" aria-hidden />
                {'\u0627\u0641\u0632\u0627\u06cc\u0634 \u0645\u0648\u062c\u0648\u062f\u06cc'}
              </Link>
            </Button>
          </Card>
        )}

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">
            {'\u062a\u0627\u0631\u06cc\u062e\u0686\u0647\u200c\u06cc \u062a\u0631\u0627\u06a9\u0646\u0634\u200c\u0647\u0627'}
          </h2>

          {!history.data ? (
            <SkeletonList count={4} />
          ) : history.data.items.length === 0 ? (
            <EmptyState
              icon={Receipt}
              title={'\u0647\u0646\u0648\u0632 \u062a\u0631\u0627\u06a9\u0646\u0634\u06cc \u062b\u0628\u062a \u0646\u0634\u062f\u0647'}
            />
          ) : (
            <ul className="space-y-2">
              {history.data.items.map((tx) => {
                const meta = KIND_META[tx.kind]
                const credit = isCredit(tx.kind)
                const Icon = meta.icon
                return (
                  <li key={tx.transactionId}>
                    <Card className="flex items-center gap-3 p-3">
                      <span
                        className={[
                          'shrink-0 rounded-lg p-2',
                          credit
                            ? 'bg-success/15 text-success'
                            : 'bg-secondary text-muted-foreground',
                        ].join(' ')}
                      >
                        <Icon className="size-4" />
                      </span>

                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">
                          {tx.descriptionFa || meta.labelFa}
                        </p>
                        <p className="nums mt-0.5 truncate text-xs text-muted-foreground">
                          {faDateTime(tx.createdAt)}
                        </p>
                      </div>

                      {/*
                        The sign is forced with an explicit + or - rather than
                        relying on the stored sign, so a debit stored as a
                        positive number can never read as a credit.
                      */}
                      <span
                        dir="ltr"
                        className={[
                          'nums shrink-0 text-sm font-semibold',
                          credit ? 'text-success' : 'text-foreground',
                        ].join(' ')}
                      >
                        {credit ? '+' : '\u2212'}
                        {toman(Math.abs(tx.amount), false)}
                      </span>
                    </Card>
                  </li>
                )
              })}
            </ul>
          )}

          {pageCount > 1 ? (
            <div className="flex items-center justify-between gap-2 pt-1">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                {'\u0642\u0628\u0644\u06cc'}
              </Button>
              <Badge variant="muted" className="nums">
                {`\u0635\u0641\u062d\u0647\u200c\u06cc ${faNumber(page)} \u0627\u0632 ${faNumber(pageCount)}`}
              </Badge>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= pageCount}
                onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
              >
                {'\u0628\u0639\u062f\u06cc'}
              </Button>
            </div>
          ) : null}
        </section>
      </div>
    </>
  )
}
