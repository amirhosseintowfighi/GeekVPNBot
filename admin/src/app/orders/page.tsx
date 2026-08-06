'use client'

import * as React from 'react'
import Link from 'next/link'
import useSWR from 'swr'
import { Search } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { faDateTime, faNumber, normalizeInput, toman, truncate } from '@/lib/fa'
import { PAYMENT_METHOD, PAYMENT_STATE, waitTone } from '@/lib/labels'
import type { OrderRow, Paged, PaymentMethod, PaymentState } from '@/lib/types'
import { PageHeader, Toolbar } from '@/components/shell/page-header'
import { EmptyState, ErrorState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { FilterSelect } from '@/components/ui/select'
import { SkeletonTable } from '@/components/ui/skeleton'
import {
  Pagination,
  SortableHead,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const PAGE_SIZE = 25

const STATE_OPTIONS = (Object.keys(PAYMENT_STATE) as PaymentState[]).map((key) => ({
  value: key,
  label: PAYMENT_STATE[key].fa,
}))

const METHOD_OPTIONS = (Object.keys(PAYMENT_METHOD) as PaymentMethod[]).map((key) => ({
  value: key,
  label: PAYMENT_METHOD[key].fa,
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
  const [state, setState] = React.useState<string | null>('pending_review')
  const [method, setMethod] = React.useState<string | null>(null)
  const [search, setSearch] = React.useState('')
  const [sort, setSort] = React.useState<{ key: string; direction: 'asc' | 'desc' }>({
    key: 'createdAt',
    direction: 'desc',
  })

  // Debounced so a typed reference does not fire a request per keystroke.
  const [debounced, setDebounced] = React.useState('')
  React.useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(normalizeInput(search))
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  const params = {
    page,
    pageSize: PAGE_SIZE,
    state,
    method,
    q: debounced,
    sort: sort.key,
    direction: sort.direction,
  }

  const { data, error, isLoading } = useSWR<Paged<OrderRow>>(
    ['orders', params],
    () => api.orders(params),
  )

  const onSort = (key: string) => {
    setSort((current) =>
      current.key === key
        ? { key, direction: current.direction === 'asc' ? 'desc' : 'asc' }
        : { key, direction: 'desc' },
    )
    setPage(1)
  }

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

          <FilterSelect
            value={method}
            onChange={(next) => {
              setMethod(next)
              setPage(1)
            }}
            options={METHOD_OPTIONS}
            allLabel={'\u0647\u0645\u0647\u0654 \u0631\u0648\u0634\u200c\u0647\u0627'}
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
                  <TableHead>{'\u06a9\u062f \u067e\u06cc\u06af\u06cc\u0631\u06cc'}</TableHead>
                  <TableHead>{'\u06a9\u0627\u0631\u0628\u0631'}</TableHead>
                  <TableHead>{'\u067e\u0644\u0646'}</TableHead>
                  <SortableHead
                    label={'\u0645\u0628\u0644\u063a'}
                    sortKey="amount"
                    activeKey={sort.key}
                    direction={sort.direction}
                    onSort={onSort}
                    numeric
                  />
                  <TableHead>{'\u0631\u0648\u0634'}</TableHead>
                  <TableHead>{'\u0648\u0636\u0639\u06cc\u062a'}</TableHead>
                  <SortableHead
                    label={'\u0632\u0645\u0627\u0646 \u0627\u0646\u062a\u0638\u0627\u0631'}
                    sortKey="waitingMinutes"
                    activeKey={sort.key}
                    direction={sort.direction}
                    onSort={onSort}
                    numeric
                  />
                  <SortableHead
                    label={'\u062a\u0627\u0631\u06cc\u062e'}
                    sortKey="createdAt"
                    activeKey={sort.key}
                    direction={sort.direction}
                    onSort={onSort}
                  />
                </TableRow>
              </TableHeader>

              <TableBody>
                {data.items.map((order) => {
                  const stateMeta = PAYMENT_STATE[order.state]
                  const methodMeta = PAYMENT_METHOD[order.method]
                  // Waiting time only means something while someone is still
                  // waiting. On a settled order it is history, so it is shown
                  // without colour.
                  const pending = order.state === 'pending_review'

                  return (
                    <TableRow key={order.id}>
                      <TableCell>
                        <Link
                          href={'/orders/' + order.id}
                          dir="ltr"
                          className="font-mono text-2xs text-primary hover:underline"
                        >
                          {order.reference}
                        </Link>
                      </TableCell>

                      <TableCell>
                        <Link href={'/users/' + order.userId} className="hover:underline">
                          {truncate(order.userFa, 24)}
                        </Link>
                      </TableCell>

                      <TableCell className="text-muted-foreground">
                        {order.planNameFa ? truncate(order.planNameFa, 28) : '\u2014'}
                      </TableCell>

                      <TableCell numeric>{toman(order.amount, false)}</TableCell>

                      <TableCell>
                        <Badge variant={methodMeta.tone}>{methodMeta.fa}</Badge>
                      </TableCell>

                      <TableCell>
                        <Badge variant={stateMeta.tone} dot>
                          {stateMeta.fa}
                        </Badge>
                      </TableCell>

                      <TableCell numeric>
                        {pending ? (
                          <Badge variant={waitTone(order.waitingMinutes)}>
                            {faNumber(order.waitingMinutes) + ' \u062f\u0642\u06cc\u0642\u0647'}
                          </Badge>
                        ) : (
                          <span className="text-muted-foreground">
                            {faNumber(order.waitingMinutes) + ' \u062f\u0642\u06cc\u0642\u0647'}
                          </span>
                        )}
                      </TableCell>

                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {faDateTime(order.createdAt)}
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
