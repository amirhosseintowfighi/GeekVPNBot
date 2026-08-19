'use client'

import * as React from 'react'
import useSWR from 'swr'

import { api, ApiError } from '@/lib/api'
import { faDateTime, normalizeInput, truncate } from '@/lib/fa'
import type { AuditLogRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader, Toolbar } from '@/components/shell/page-header'
import { EmptyState, ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { SkeletonTable } from '@/components/ui/skeleton'
import { Pagination, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const PAGE_SIZE = 25


/**
 * Audit log.
 *
 * Two things make this screen useful rather than decorative:
 *
 * 1. Before/after values. "Operator X changed a price" is a rumour; "changed
 *    it from 680,000 to 68,000" is an explanation. Each changed field is
 *    listed with both values, old struck through.
 * 2. The correlation id. One customer action fans out into a payment
 *    approval, a panel call and a notification. The id ties them together, is
 *    rendered LTR and monospaced, and is what gets pasted into a search when
 *    something went wrong halfway through.
 *
 * Rows expand rather than link: an audit entry has no life of its own, and a
 * detail page for one would just be this row on a bigger canvas.
 */
export default function LogsPage() {
  const { can } = useSession()
  const [page, setPage] = React.useState(1)
  const [search, setSearch] = React.useState('')
  const [expanded, setExpanded] = React.useState<string | null>(null)

  const [debounced, setDebounced] = React.useState('')
  React.useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(normalizeInput(search))
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  const { data, error, isLoading } = useSWR<AuditLogRow[]>(['logs', page, debounced], () =>
    api.logs({ page, pageSize: PAGE_SIZE, action: debounced || undefined }),
  )

  if (!can('logs.view')) return <ForbiddenState permission="logs.view" />

  return (
    <>
      <PageHeader
        title={'\u0644\u0627\u06af\u200c\u0647\u0627'}
        description={'\u0631\u062f\u067e\u0627\u06cc \u062a\u0645\u0627\u0645 \u062a\u063a\u06cc\u06cc\u0631\u0627\u062a \u0648 \u0627\u0642\u062f\u0627\u0645\u0627\u062a \u0627\u067e\u0631\u0627\u062a\u0648\u0631\u0647\u0627'}
      />

      <Card>
        <Toolbar>
          <div className="min-w-48 flex-1 sm:max-w-72">
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={'\u062c\u0633\u062a\u062c\u0648\u06cc \u0627\u0642\u062f\u0627\u0645\u060c \u0627\u067e\u0631\u0627\u062a\u0648\u0631 \u06cc\u0627 \u0634\u0646\u0627\u0633\u0647\u0654 \u0647\u0645\u0628\u0633\u062a\u06af\u06cc'}
              className="h-8 text-2xs"
            />
          </div>

        </Toolbar>

        {error ? (
          <ErrorState
            messageFa={error instanceof ApiError ? error.messageFa : ''}
            offline={error instanceof ApiError && error.status === 0}
            onRetry={() => window.location.reload()}
          />
        ) : isLoading && !data ? (
          <SkeletonTable rows={12} cols={5} />
        ) : !data || data.length === 0 ? (
          <EmptyState title={'\u0644\u0627\u06af\u06cc \u06cc\u0627\u0641\u062a \u0646\u0634\u062f'} />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{'\u0646\u062a\u06cc\u062c\u0647'}</TableHead>
                  <TableHead>{'\u0627\u0642\u062f\u0627\u0645'}</TableHead>
                  <TableHead>{'\u0627\u067e\u0631\u0627\u062a\u0648\u0631'}</TableHead>
                  <TableHead>{'\u0645\u0648\u0636\u0648\u0639'}</TableHead>
                  <TableHead>{'\u0632\u0645\u0627\u0646'}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((row) => {
                  // The trail records an outcome, not a severity, and carries
                  // a free-form metadata object rather than a field-level diff.
                  const open = expanded === row.id
                  const failed = row.outcome !== 'success'
                  return (
                    <React.Fragment key={row.id}>
                      <TableRow selected={open}>
                        <TableCell>
                          <Badge variant={failed ? 'destructive' : 'success'} dot>
                            {row.outcome}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <button
                            type="button"
                            onClick={() => setExpanded(open ? null : row.id)}
                            className="text-start hover:underline"
                          >
                            <span dir="ltr" className="font-mono text-2xs">
                              {row.action}
                            </span>
                          </button>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {row.actorLabel ?? row.actorType}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {truncate(
                            row.targetType ? row.targetType + ' ' + (row.targetId ?? '') : '\u2014',
                            30,
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-muted-foreground">
                          {faDateTime(row.occurredAt)}
                        </TableCell>
                      </TableRow>

                      {open ? (
                        <TableRow>
                          <TableCell colSpan={5} className="bg-muted/30">
                            <div className="space-y-2 py-1">
                              <p className="text-2xs text-muted-foreground">
                                {'\u0634\u0646\u0627\u0633\u0647\u0654 \u0647\u0645\u0628\u0633\u062a\u06af\u06cc: '}
                                <span dir="ltr" className="font-mono">{row.correlationId ?? '\u2014'}</span>
                                {row.ip ? (
                                  <>
                                    {' \u00b7 IP: '}
                                    <span dir="ltr" className="font-mono">{row.ip}</span>
                                  </>
                                ) : null}
                              </p>

                              {Object.keys(row.metadata).length === 0 ? (
                                <p className="text-2xs text-muted-foreground">
                                  {'\u0627\u06cc\u0646 \u0627\u0642\u062f\u0627\u0645 \u062c\u0632\u0626\u06cc\u0627\u062a \u0628\u06cc\u0634\u062a\u0631\u06cc \u062b\u0628\u062a \u0646\u06a9\u0631\u062f\u0647 \u0627\u0633\u062a.'}
                                </p>
                              ) : (
                                <ul className="space-y-1">
                                  {Object.entries(row.metadata).map(([key, value]) => (
                                    <li key={key} className="flex flex-wrap items-center gap-2 text-2xs">
                                      <span className="text-muted-foreground">{key}</span>
                                      <span dir="ltr" className="nums font-mono">
                                        {String(value)}
                                      </span>
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      ) : null}
                    </React.Fragment>
                  )
                })}
              </TableBody>
            </Table>

            {/* The endpoint returns a list, not a count, so paging is
                "is this page full" rather than a total. */}
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={(page - 1) * PAGE_SIZE + data.length + (data.length === PAGE_SIZE ? 1 : 0)}
              onPageChange={setPage}
            />
          </>
        )}
      </Card>
    </>
  )
}
