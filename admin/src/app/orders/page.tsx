'use client'

import * as React from 'react'
import Link from 'next/link'
import useSWR from 'swr'
import { Search } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { faDateTime, normalizeInput, toman, truncate } from '@/lib/fa'
import { ORDER_STATE } from '@/lib/labels'
import type { OrderRow, OrderState, Paged } from '@/lib/types'
import { PageHeader, Toolbar } from '@/components/shell/page-header'
import { EmptyState, ErrorState } from '@/components/shell/states'
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

const PAGE_SIZE = 25

const STATE_OPTIONS = (Object.keys(ORDER_STATE) as OrderState[]).map((key) => ({
  value: key,
  label: ORDER_STATE[key].fa,
}))

/**
 * Orders - the manual approval queue.
 *
 * This is the single most operationally important screen in the panel. Every
 * card-to-card payment and every crypto transfer passes through a human here,
 * and a customer is waiting at the other end of each row.
 *
 * Two decisions follow from that:
 *
 * 1. The default filter is `pending_review`, not "all". An operator opening
 *    this screen is almost always here to clear the queue, and showing three
 *    months of settled orders first makes them filter before they can work.
 * 2. Waiting time is a first-class column with its own colour, driven by the
 *    thirty-minute promise the FAQ makes to customers. It is the field that
 *    decides which row to open next.
 *
 * Rows link to a detail page rather than opening a dialog: approving a
 * payment means reading a receipt image and a txid, which needs room and a
 * URL an operator can paste to a colleague.
 */
export default function OrdersPage() {
  const [page, setPage] = React.useState(1)
  // `paid` is the queue that needs a human: money is in, service is not out.
  // The default used to be 'pending_review', which is a *payment* state and
  // matches no order.
  const [state, setState] = React.useState<string | undefined>('paid')
  const [search, setSearch] = React.useState('')

  // Debounced so a typed reference does not fire a request per keystroke.
  const [debounced, setDebounced] = React.useState('')
  React.useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(normalizeInput(search))
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  // state, number, limit and offset - the whole of what GET /orders accepts.
  // No method filter and no sorting: neither exists on the endpoint.
  const params = { page, pageSize: PAGE_SIZE, state, number: debounced }

  const { data, error, isLoading } = useSWR<Paged<OrderRow>>(
    ['orders', params],
    () => api.orders(params),
  )


  return (
    <>
      <PageHeader
        title={'\u0633\u0641\u0627\u0631\u0634\u200c\u0647\u0627'}
        description={
          '\u0628\u0631\u0631\u0633\u06cc \u062f\u0633\u062a\u06cc \u067e\u0631\u062f\u0627\u062e\u062a\u200c\u0647\u0627\u06cc \u06a9\u0627\u0631\u062a \u0628\u0647 \u06a9\u0627\u0631\u062a \u0648 \u0631\u0645\u0632\u0627\u0631\u0632'
        }
      />

      <Card>
        <Toolbar>
          <div className="relative min-w-48 flex-1 sm:max-w-72">
            <Search className="pointer-events-none absolute end-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={'\u062c\u0633\u062a\u062c\u0648\u06cc \u06a9\u062f \u067e\u06cc\u06af\u06cc\u0631\u06cc \u06cc\u0627 \u06a9\u0627\u0631\u0628\u0631'}
              className="h-8 pe-8 text-2xs"
            />
          </div>

          <FilterSelect
            value={state}
            onChange={(next) => {
              setState(next)
              setPage(1)
            }}
            options={STATE_OPTIONS}
            allLabel={'\u0647\u0645\u0647\u0654 \u0648\u0636\u0639\u06cc\u062a\u200c\u0647\u0627'}
          />

        </Toolbar>

        {error ? (
          <ErrorState
            messageFa={error instanceof ApiError ? error.messageFa : ''}
            offline={error instanceof ApiError && error.status === 0}
            onRetry={() => window.location.reload()}
          />
        ) : isLoading && !data ? (
          <SkeletonTable rows={10} cols={7} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title={'\u0633\u0641\u0627\u0631\u0634\u06cc \u06cc\u0627\u0641\u062a \u0646\u0634\u062f'}
            description={
              '\u0628\u0627 \u0627\u06cc\u0646 \u0641\u06cc\u0644\u062a\u0631\u0647\u0627 \u0633\u0641\u0627\u0631\u0634\u06cc \u0648\u062c\u0648\u062f \u0646\u062f\u0627\u0631\u062f. \u0627\u06af\u0631 \u0635\u0641 \u0628\u0631\u0631\u0633\u06cc \u062e\u0627\u0644\u06cc \u0627\u0633\u062a\u060c \u06a9\u0627\u0631 \u062a\u0645\u0627\u0645 \u0627\u0633\u062a.'
            }
          />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{'\u0634\u0645\u0627\u0631\u0647'}</TableHead>
                  <TableHead>{'\u06a9\u0627\u0631\u0628\u0631'}</TableHead>
                  <TableHead>{'\u067e\u0644\u0646'}</TableHead>
                  <TableHead numeric>{'\u0645\u0628\u0644\u063a'}</TableHead>
                  <TableHead>{'\u062a\u062e\u0641\u06cc\u0641'}</TableHead>
                  <TableHead>{'\u0648\u0636\u0639\u06cc\u062a'}</TableHead>
                  <TableHead>{'\u062b\u0628\u062a'}</TableHead>
                </TableRow>
              </TableHeader>

              <TableBody>
                {data.items.map((order) => {
                  const stateMeta = ORDER_STATE[order.state]

                  return (
                    <TableRow key={order.id}>
                      <TableCell>
                        <Link
                          href={'/orders/' + order.id}
                          dir="ltr"
                          className="font-mono text-2xs text-primary hover:underline"
                        >
                          {order.number}
                        </Link>
                      </TableCell>

                      <TableCell>
                        <Link href={'/users/' + order.userId} className="hover:underline">
                          {order.userId}
                        </Link>
                      </TableCell>

                      <TableCell className="text-muted-foreground">
                        {truncate(order.planNameFa, 28)}
                      </TableCell>

                      <TableCell numeric>{toman(order.total, false)}</TableCell>

                      <TableCell numeric className="text-muted-foreground">
                        {order.discount > 0 ? toman(order.discount, false) : '\u2014'}
                      </TableCell>

                      <TableCell>
                        <Badge variant={stateMeta.tone} dot>
                          {stateMeta.fa}
                        </Badge>
                      </TableCell>

                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {faDateTime(order.placedAt)}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>

            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={data.total}
              onPageChange={setPage}
            />
          </>
        )}
      </Card>
    </>
  )
}
