'use client'

import * as React from 'react'
import useSWR from 'swr'

import { api, ApiError } from '@/lib/api'
import { faDateTime, normalizeInput, truncate } from '@/lib/fa'
import { LOG_LEVEL } from '@/lib/labels'
import type { AuditLogRow, LogLevel, Paged } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader, Toolbar } from '@/components/shell/page-header'
import { EmptyState, ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { FilterSelect } from '@/components/ui/select'
import { SkeletonTable } from '@/components/ui/skeleton'
import { Pagination, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const PAGE_SIZE = 25

const LEVEL_OPTIONS = (Object.keys(LOG_LEVEL) as LogLevel[]).map((key) => ({
  value: key,
  label: LOG_LEVEL[key].fa,
}))

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
  const [level, setLevel] = React.useState<string | null>(null)
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

  const params = { page, pageSize: PAGE_SIZE, level, q: debounced }
  const { data, error, isLoading } = useSWR<Paged<AuditLogRow>>(['logs', params], () => api.logs(params))

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

          <FilterSelect
            value={level}
            onChange={(next) => {
              setLevel(next)
              setPage(1)
            }}
            options={LEVEL_OPTIONS}
            allLabel={'\u0647\u0645\u0647\u0654 \u0633\u0637\u0648\u062d'}
          />
        </Toolbar>

        {error ? (
          <ErrorState
            messageFa={error instanceof ApiError ? error.messageFa : ''}
            offline={error instanceof ApiError && error.status === 0}
            onRetry={() => window.location.reload()}
          />
        ) : isLoading && !data ? (
          <SkeletonTable rows={12} cols={5} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState title={'\u0644\u0627\u06af\u06cc \u06cc\u0627\u0641\u062a \u0646\u0634\u062f'} />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{'\u0633\u0637\u062d'}</TableHead>
                  <TableHead>{'\u0627\u0642\u062f\u0627\u0645'}</TableHead>
                  <TableHead>{'\u0627\u067e\u0631\u0627\u062a\u0648\u0631'}</TableHead>
                  <TableHead>{'\u0645\u0648\u0636\u0648\u0639'}</TableHead>
                  <TableHead>{'\u0632\u0645\u0627\u0646'}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((row) => {
                  const meta = LOG_LEVEL[row.level]
                  const open = expanded === row.id
                  return (
                    <React.Fragment key={row.id}>
                      <TableRow selected={open}>
                        <TableCell>
                          <Badge variant={meta.tone} dot>
                            {meta.fa}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <button
                            type="button"
                            onClick={() => setExpanded(open ? null : row.id)}
                            className="text-start hover:underline"
                          >
                            {row.actionFa}
                          </button>
                        </TableCell>
                        <TableCell className="text-muted-foreground">{row.actorFa}</TableCell>
                        <TableCell className="text-muted-foreground">
                          {truncate(row.targetFa ?? '\u2014', 30)}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-muted-foreground">
                          {faDateTime(row.createdAt)}
                        </TableCell>
                      </TableRow>

                      {open ? (
                        <TableRow>
                          <TableCell colSpan={5} className="bg-muted/30">
                            <div className="space-y-2 py-1">
                              <p className="text-2xs text-muted-foreground">
                                {'\u0634\u0646\u0627\u0633\u0647\u0654 \u0647\u0645\u0628\u0633\u062a\u06af\u06cc: '}
                                <span dir="ltr" className="font-mono">{row.correlationId}</span>
                              </p>

                              {row.changes.length === 0 ? (
                                <p className="text-2xs text-muted-foreground">
                                  {'\u0627\u06cc\u0646 \u0627\u0642\u062f\u0627\u0645 \u062a\u063a\u06cc\u06cc\u0631 \u0645\u06cc\u062f\u0627\u0646\u06cc \u062b\u0628\u062a \u0646\u06a9\u0631\u062f\u0647 \u0627\u0633\u062a.'}
                                </p>
                              ) : (
                                <ul className="space-y-1">
                                  {row.changes.map((change, index) => (
                                    <li key={index} className="flex flex-wrap items-center gap-2 text-2xs">
                                      <span className="text-muted-foreground">{change.fieldFa}</span>
                                      <span className="nums text-destructive line-through">
                                        {change.beforeFa ?? '\u2014'}
                                      </span>
                                      <span aria-hidden>{'\u2190'}</span>
                                      <span className="nums text-success">{change.afterFa ?? '\u2014'}</span>
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

            <Pagination page={data.page} pageSize={data.pageSize} total={data.total} onPageChange={setPage} />
          </>
        )}
      </Card>
    </>
  )
}
