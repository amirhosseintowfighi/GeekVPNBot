'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Search } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { faDateTime, faNumber, normalizeInput, toman } from '@/lib/fa'
import { TRANSACTION_KIND } from '@/lib/labels'
import type { PagedWithCursor, TransactionKind, WalletTransactionRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader, Toolbar } from '@/components/shell/page-header'
import { EmptyState, ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { FilterSelect } from '@/components/ui/select'
import { SkeletonTable } from '@/components/ui/skeleton'
import {
  Pagination,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const KIND_OPTIONS = (Object.keys(TRANSACTION_KIND) as TransactionKind[]).map((key) => ({
  value: key,
  label: TRANSACTION_KIND[key].fa,
}))

/**
 * One customer's wallet ledger.
 *
 * Scoped to a customer because that is the only ledger the API has: every
 * wallet route is `/wallet/{userId}/...`. This screen used to ask for a global
 * journal of every movement of customer money across all accounts, from
 * `/wallet/transactions`, which is not a route and never has been.
 *
 * Adjustments stay on the user's own page. Correcting a balance requires
 * seeing whose balance it is; an adjust control on a ledger you arrived at by
 * typing an id is how the wrong account gets credited.
 *
 * The running balance is shown per row because the question asked of this
 * screen is almost never "what happened" but "how did the balance get here".
 */
export default function WalletPage() {
  const { can } = useSession()
  const [page, setPage] = React.useState(1)
  const [kind, setKind] = React.useState<string | undefined>(undefined)
  const [search, setSearch] = React.useState('')

  // The Telegram id, which is what the wallet is keyed on. Debounced so typing
  // an id does not fire a request per digit.
  const [userId, setUserId] = React.useState('')
  React.useEffect(() => {
    const timer = setTimeout(() => {
      setUserId(normalizeInput(search).replace(/\D/g, ''))
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  const { data, error, isLoading } = useSWR<PagedWithCursor<WalletTransactionRow>>(
    userId ? ['wallet', userId, page, kind] : null,
    () => api.walletStatement(userId, { page, kind }),
  )

  const { data: balance } = useSWR(
    userId ? ['wallet-balance', userId] : null,
    () => api.walletBalance(userId),
  )

  if (!can('wallet.read')) return <ForbiddenState permission="wallet.read" />

  return (
    <>
      <PageHeader
        title={'کیف پول'}
        description={
          balance ? 'موجودی: ' + toman(balance.balance) : 'شناسهٔ تلگرام کاربر را وارد کنید'
        }
      />

      <Card>
        <Toolbar>
          <div className="relative min-w-48 flex-1 sm:max-w-72">
            <Search className="pointer-events-none absolute end-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={'شناسهٔ تلگرام'}
              className="h-8 pe-8 text-2xs"
              dir="ltr"
              inputMode="numeric"
            />
          </div>

          <FilterSelect
            value={kind}
            onChange={(next) => {
              setKind(next)
              setPage(1)
            }}
            options={KIND_OPTIONS}
            allLabel={'همهٔ تراکنش‌ها'}
          />
        </Toolbar>

        {!userId ? (
          <EmptyState
            title={'کاربری انتخاب نشده'}
            description={'برای دیدن دفتر کیف پول، شناسهٔ تلگرام کاربر را وارد کنید.'}
          />
        ) : error ? (
          <ErrorState
            messageFa={error instanceof ApiError ? error.messageFa : ''}
            offline={error instanceof ApiError && error.status === 0}
            onRetry={() => window.location.reload()}
          />
        ) : isLoading && !data ? (
          <SkeletonTable rows={10} cols={5} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState title={'تراکنشی ثبت نشده'} />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{'نوع'}</TableHead>
                  <TableHead numeric>{'مبلغ'}</TableHead>
                  <TableHead numeric>{'موجودی پس از آن'}</TableHead>
                  <TableHead>{'شرح'}</TableHead>
                  <TableHead>{'زمان'}</TableHead>
                </TableRow>
              </TableHeader>

              <TableBody>
                {data.items.map((entry) => {
                  const meta = TRANSACTION_KIND[entry.kind]
                  return (
                    <TableRow key={entry.entryId}>
                      <TableCell>
                        <Badge variant={meta.tone}>{meta.fa}</Badge>
                      </TableCell>

                      {/* A credit and a debit must not look alike on a money
                          screen, so the sign carries the colour. */}
                      <TableCell numeric className={entry.isCredit ? 'text-success' : 'text-destructive'}>
                        {(entry.isCredit ? '+' : '') + toman(entry.amount, false)}
                      </TableCell>

                      <TableCell numeric>{toman(entry.balanceAfter, false)}</TableCell>

                      <TableCell className="text-muted-foreground">
                        {entry.descriptionFa ?? '—'}
                        {entry.actorId ? (
                          <span className="ms-1 text-2xs">
                            {'· توسط ' + faNumber(Number(entry.actorId))}
                          </span>
                        ) : null}
                      </TableCell>

                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {faDateTime(entry.occurredAt)}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>

            <Pagination
              page={data.page}
              pageSize={data.pageSize}
              total={data.total}
              onPageChange={setPage}
            />
          </>
        )}
      </Card>
    </>
  )
}
