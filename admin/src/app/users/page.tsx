'use client'

import * as React from 'react'
import Link from 'next/link'
import useSWR from 'swr'
import { Search } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { faDate, faNumber, normalizeInput, truncate } from '@/lib/fa'
import { USER_STATE } from '@/lib/labels'
import type { Paged, UserRow, UserState } from '@/lib/types'
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

const STATE_OPTIONS = (Object.keys(USER_STATE) as UserState[]).map((key) => ({
  value: key,
  label: USER_STATE[key].fa,
}))


/**
 * Users.
 *
 * Search accepts a Telegram id, a username or a display name, and every
 * query is pushed through `normalizeInput` first: operators paste ids out of
 * the bot, which renders them in Persian digits, and ۱۲۳ must find 123.
 */
export default function UsersPage() {
  const [page, setPage] = React.useState(1)
  // No tier filter and no sort state: GET /customers takes status, query,
  // limit and offset, and nothing else. Both were being sent and silently
  // dropped, so the screen offered controls that changed nothing.
  const [status, setStatus] = React.useState<string | undefined>(undefined)
  const [search, setSearch] = React.useState('')

  const [debounced, setDebounced] = React.useState('')
  React.useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(normalizeInput(search))
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  const params = { page, pageSize: PAGE_SIZE, status, query: debounced }

  const { data, error, isLoading } = useSWR<Paged<UserRow>>(['users', params], () => api.users(params))

  return (
    <>
      <PageHeader
        title={'\u06a9\u0627\u0631\u0628\u0631\u0627\u0646'}
        description={data ? faNumber(data.total) + ' \u06a9\u0627\u0631\u0628\u0631' : undefined}
      />

      <Card>
        <Toolbar>
          <div className="relative min-w-48 flex-1 sm:max-w-72">
            <Search className="pointer-events-none absolute end-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={'\u0634\u0646\u0627\u0633\u0647\u060c \u0646\u0627\u0645 \u06a9\u0627\u0631\u0628\u0631\u06cc \u06cc\u0627 \u0646\u0627\u0645'}
              className="h-8 pe-8 text-2xs"
            />
          </div>

          <FilterSelect
            value={status}
            onChange={(next) => {
              setStatus(next)
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
          <SkeletonTable rows={10} cols={6} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title={'\u06a9\u0627\u0631\u0628\u0631\u06cc \u06cc\u0627\u0641\u062a \u0646\u0634\u062f'}
            description={'\u062c\u0633\u062a\u062c\u0648 \u06cc\u0627 \u0641\u06cc\u0644\u062a\u0631\u0647\u0627 \u0631\u0627 \u062a\u063a\u06cc\u06cc\u0631 \u062f\u0647\u06cc\u062f.'}
          />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{'\u06a9\u0627\u0631\u0628\u0631'}</TableHead>
                  <TableHead>{'\u0634\u0646\u0627\u0633\u0647\u0654 \u062a\u0644\u06af\u0631\u0627\u0645'}</TableHead>
                  <TableHead>{'\u0648\u0636\u0639\u06cc\u062a'}</TableHead>
                  <TableHead>{'\u0645\u0639\u0631\u0641'}</TableHead>
                  <TableHead>{'\u0622\u062e\u0631\u06cc\u0646 \u0628\u0627\u0632\u062f\u06cc\u062f'}</TableHead>
                  <TableHead>{'\u0639\u0636\u0648\u06cc\u062a'}</TableHead>
                </TableRow>
              </TableHeader>

              <TableBody>
                {data.items.map((user) => {
                  const stateMeta = USER_STATE[user.status]
                  return (
                    <TableRow key={user.id}>
                      <TableCell>
                        <Link href={'/users/' + user.id} className="text-primary hover:underline">
                          {truncate(user.displayName, 26)}
                        </Link>
                        {user.username ? (
                          <span dir="ltr" className="ms-1 font-mono text-2xs text-muted-foreground">
                            @{user.username}
                          </span>
                        ) : null}
                      </TableCell>

                      <TableCell>
                        <span dir="ltr" className="font-mono text-2xs text-muted-foreground">
                          {user.telegramId}
                        </span>
                      </TableCell>

                      <TableCell>
                        <Badge variant={stateMeta.tone} dot>
                          {stateMeta.fa}
                        </Badge>
                      </TableCell>

                      <TableCell>
                        <span dir="ltr" className="font-mono text-2xs text-muted-foreground">
                          {user.referredByCode ?? '\u2014'}
                        </span>
                      </TableCell>

                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {user.lastSeenAt ? faDate(user.lastSeenAt) : '\u2014'}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {faDate(user.createdAt)}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>

            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPageChange={setPage} />
          </>
        )}
      </Card>
    </>
  )
}
