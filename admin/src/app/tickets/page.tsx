'use client'

import * as React from 'react'
import Link from 'next/link'
import useSWR from 'swr'

import { api, ApiError } from '@/lib/api'
import { faNumber, faRelative, truncate } from '@/lib/fa'
import { TICKET_STATE, waitTone } from '@/lib/labels'
import type { AdminTicketRow, PagedWithCursor } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader, Toolbar } from '@/components/shell/page-header'
import { EmptyState, ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { FilterSelect } from '@/components/ui/select'
import { SkeletonTable } from '@/components/ui/skeleton'
import { Pagination, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

// The queue filters by category, not by state: it is the *open* queue, and
// every ticket in it is open by definition.
const CATEGORY_OPTIONS = [
  { value: 'connection', label: 'اتصال' },
  { value: 'payment', label: 'پرداخت' },
  { value: 'account', label: 'حساب' },
  { value: 'speed', label: 'سرعت' },
  { value: 'technical', label: 'فنی' },
  { value: 'other', label: 'سایر' },
]

/**
 * Tickets.
 *
 * Like orders, this is a queue with a person waiting in it, so it defaults to
 * `open` and sorts oldest-first: a ticket that has been waiting two days is
 * more urgent than one that arrived a minute ago, and a newest-first list
 * buries exactly the customers who are already unhappy.
 */
export default function TicketsPage() {
  const { can } = useSession()
  const [page, setPage] = React.useState(1)
  const [category, setCategory] = React.useState<string | undefined>(undefined)

  const { data, error, isLoading } = useSWR<PagedWithCursor<AdminTicketRow>>(
    ['tickets', page, category],
    () => api.tickets({ page, category }),
  )

  if (!can('tickets.read')) return <ForbiddenState permission="tickets.read" />

  return (
    <>
      <PageHeader
        title={'\u062a\u06cc\u06a9\u062a\u200c\u0647\u0627'}
        description={'\u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc \u06a9\u0627\u0631\u0628\u0631\u0627\u0646\u061b \u0642\u062f\u06cc\u0645\u06cc\u200c\u062a\u0631\u06cc\u0646 \u062f\u0631 \u0628\u0627\u0644\u0627'}
      />

      <Card>
        <Toolbar>
          <FilterSelect
            value={category}
            onChange={(next) => {
              setCategory(next)
              setPage(1)
            }}
            options={CATEGORY_OPTIONS}
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
          <SkeletonTable rows={10} cols={5} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title={'\u062a\u06cc\u06a9\u062a\u06cc \u0646\u06cc\u0633\u062a'}
            description={'\u0635\u0641 \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc \u062e\u0627\u0644\u06cc \u0627\u0633\u062a.'}
          />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{'\u0645\u0648\u0636\u0648\u0639'}</TableHead>
                  <TableHead>{'\u06a9\u0627\u0631\u0628\u0631'}</TableHead>
                  <TableHead>{'\u0648\u0636\u0639\u06cc\u062a'}</TableHead>
                  <TableHead>{'\u067e\u06cc\u0627\u0645'}</TableHead>
                  <TableHead>{'\u0645\u0646\u062a\u0638\u0631'}</TableHead>
                  <TableHead>{'\u0622\u062e\u0631\u06cc\u0646 \u067e\u06cc\u0627\u0645'}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((ticket) => {
                  const meta = TICKET_STATE[ticket.state]
                  // Only colour the wait while the ball is in our court, and
                  // only when there is a wait: an answered ticket has none.
                  const ours = ticket.state === 'open'
                  const waiting = ticket.waitingMinutes
                  return (
                    <TableRow key={ticket.ticketId}>
                      <TableCell>
                        <Link
                          href={'/tickets/' + ticket.ticketId}
                          className="text-primary hover:underline"
                        >
                          {truncate(ticket.subjectFa, 40)}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <Link
                          href={'/users/' + ticket.userId}
                          className="hover:underline"
                        >
                          {ticket.customerName ?? faNumber(ticket.userId)}
                        </Link>
                        {ticket.customerUsername ? (
                          <span dir="ltr" className="block text-2xs text-muted-foreground">
                            {'@' + ticket.customerUsername}
                          </span>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        <Badge variant={meta.tone} dot>
                          {meta.fa}
                        </Badge>
                      </TableCell>
                      <TableCell numeric>{faNumber(ticket.messageCount)}</TableCell>
                      <TableCell numeric>
                        {waiting === null ? (
                          <span className="text-muted-foreground">{'\u2014'}</span>
                        ) : ours ? (
                          <Badge variant={waitTone(waiting)}>
                            {faNumber(waiting) + ' \u062f\u0642\u06cc\u0642\u0647'}
                          </Badge>
                        ) : (
                          <span className="text-muted-foreground">
                            {faNumber(waiting) + ' \u062f\u0642\u06cc\u0642\u0647'}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {faRelative(ticket.updatedAt)}
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
