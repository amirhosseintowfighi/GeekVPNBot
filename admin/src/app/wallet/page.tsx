'use client'

import * as React from 'react'
import Link from 'next/link'
import useSWR from 'swr'

import { api, ApiError } from '@/lib/api'
import { faDateTime, toman, truncate } from '@/lib/fa'
import { TRANSACTION_KIND } from '@/lib/labels'
import type { Paged, TransactionKind, WalletTransactionRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader, Toolbar } from '@/components/shell/page-header'
import { EmptyState, ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { FilterSelect } from '@/components/ui/select'
import { SkeletonTable } from '@/components/ui/skeleton'
import { Pagination, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const PAGE_SIZE = 25

const KIND_OPTIONS = (Object.keys(TRANSACTION_KIND) as TransactionKind[]).map((key) => ({
  value: key,
  label: TRANSACTION_KIND[key].fa,
}))

/**
 * Wallet ledger.
 *
 * A read-only journal of every movement of customer money. Adjustments are
 * made from the user's own page, not here, and deliberately so: adjusting a
 * balance requires seeing whose balance it is, what they bought and what
 * their orders look like. A bulk "adjust" control on a global ledger is an
 * invitation to credit the wrong account.
 *
 * The running balance is shown per row because the question asked of this
 * screen is almost never "what happened" but "how did the balance get here".
 */
export default function WalletPage() {
  const { can } = useSession()
  const [page, setPage] = React.useState(1)
  const [kind, setKind] = React.useState<string | null>(null)

  const params = { page, pageSize: PAGE_SIZE, kind }
  const { data, error, isLoading } = useSWR<Paged<WalletTransactionRow>>(
    ['wallet', params],
    () => api.walletTransactions(params),
  )

  if (!can('wallet.view')) return <ForbiddenState permission="wallet.view" />

  return (
    <>
      <PageHeader
        title={'\u06a9\u06cc\u0641 \u067e\u0648\u0644'}
        description={'\u062f\u0641\u062a\u0631 \u062a\u0631\u0627\u06a9\u0646\u0634\u200c\u0647\u0627\u06cc \u0645\u0627\u0644\u06cc \u06a9\u0627\u0631\u0628\u0631\u0627\u0646'}
      />

      <Card>
        <Toolbar>
          <FilterSelect
            value={kind}
            onChange={(next) => {
              setKind(next)
              setPage(1)
            }}
            options={KIND_OPTIONS}
            allLabel={'\u0647\u0645\u0647\u0654 \u0627\u0646\u0648\u0627\u0639'}
          />
        </Toolbar>

        {error ? (
          <ErrorState
            messageFa={error instanceof ApiError ? error.messageFa : ''}
            offline={error instanceof ApiError && error.status === 0}
            onRetry={() => window.location.reload()}
          />
        ) : isLoading && !data ? (
          <SkeletonTable rows={10} cols={6} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState title={'\u062a\u0631\u0627\u06a9\u0646\u0634\u06cc \u06cc\u0627\u0641\u062a \u0646\u0634\u062f'} />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{'\u06a9\u0627\u0631\u0628\u0631'}</TableHead>
                  <TableHead>{'\u0646\u0648\u0639'}</TableHead>
                  <TableHead>{'\u0645\u0628\u0644\u063a'}</TableHead>
                  <TableHead>{'\u0645\u0648\u062c\u0648\u062f\u06cc \u067e\u0633 \u0627\u0632 \u0622\u0646'}</TableHead>
                  <TableHead>{'\u062a\u0648\u0636\u06cc\u062d'}</TableHead>
                  <TableHead>{'\u062a\u0627\u0631\u06cc\u062e'}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((row) => {
                  const meta = TRANSACTION_KIND[row.kind]
                  const credit = row.amount > 0
                  return (
                    <TableRow key={row.id}>
                      <TableCell>
                        <Link href={'/users/' + row.userId} className="text-primary hover:underline">
                          {truncate(row.userFa, 22)}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <Badge variant={meta.tone}>{meta.fa}</Badge>
                      </TableCell>
                      {/* Sign carries the meaning; colour only reinforces it.
                          Credits green, debits plain - a red debit would read
                          as an error rather than a normal purchase. */}
                      <TableCell numeric className={credit ? 'text-success' : ''}>
                        {(credit ? '+' : '') + toman(row.amount, false)}
                      </TableCell>
                      <TableCell numeric className="text-muted-foreground">
                        {toman(row.balanceAfter, false)}
                      </TableCell>
                      <TableCell className="max-w-64 truncate text-muted-foreground">
                        {row.descriptionFa}
                        {/* Manual adjustments name the operator: this is the
                            audit trail people actually read. */}
                        {row.kind === 'adjustment' && row.actorFa ? (
                          <span className="ms-1 text-warning">{'\u00b7 ' + row.actorFa}</span>
                        ) : null}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {faDateTime(row.createdAt)}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>

            <Pagination page={data.page} pageSize={data.pageSize} total={data.total} onPageChange={setPage} />
          </>
        )}
      </Card>
    </>
  )
}
