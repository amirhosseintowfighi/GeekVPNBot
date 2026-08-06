'use client'

import * as React from 'react'
import Link from 'next/link'
import useSWR from 'swr'
import { Search } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { faDate, faNumber, normalizeInput, toman, truncate } from '@/lib/fa'
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
  SortableHead,
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

const TIER_OPTIONS = [
  { value: 'bronze', label: '\u0628\u0631\u0646\u0632\u06cc' },
  { value: 'silver', label: '\u0646\u0642\u0631\u0647\u200c\u0627\u06cc' },
  { value: 'gold', label: '\u0637\u0644\u0627\u06cc\u06cc' },
  { value: 'diamond', label: '\u0627\u0644\u0645\u0627\u0633\u06cc' },
]

/**
 * Users.
 *
 * Search accepts a Telegram id, a username or a display name, and every
 * query is pushed through `normalizeInput` first: operators paste ids out of
 * the bot, which renders them in Persian digits, and ۱۲۳ must find 123.
 */
export default function UsersPage() {
  const [page, setPage] = React.useState(1)
  const [state, setState] = React.useState<string | null>(null)
  const [tier, setTier] = React.useState<string | null>(null)
  const [search, setSearch] = React.useState('')
  const [sort, setSort] = React.useState<{ key: string; direction: 'asc' | 'desc' }>({
    key: 'createdAt',
    direction: 'desc',
  })

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
    tier,
    q: debounced,
    sort: sort.key,
    direction: sort.direction,
  }

  const { data, error, isLoading } = useSWR<Paged<UserRow>>(['users', params], () => api.users(params))

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
            value={state}
            onChange={(next) => {
              setState(next)
              setPage(1)
            }}
            options={STATE_OPTIONS}
            allLabel={'\u0647\u0645\u0647\u0654 \u0648\u0636\u0639\u06cc\u062a\u200c\u0647\u0627'}
          />

          <FilterSelect
            value={tier}
            onChange={(next) => {
              setTier(next)
              setPage(1)
            }}
            options={TIER_OPTIONS}
            allLabel={'\u0647\u0645\u0647\u0654 \u0633\u0637\u062d\u200c\u0647\u0627'}
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
                  <TableHead>{'\u0633\u0637\u062d'}</TableHead>
                  <SortableHead
                    label={'\u0627\u0634\u062a\u0631\u0627\u06a9 \u0641\u0639\u0627\u0644'}
                    sortKey="activeSubscriptions"
                    activeKey={sort.key}
                    direction={sort.direction}
                    onSort={onSort}
                    numeric
                  />
                  <SortableHead
                    label={'\u0645\u062c\u0645\u0648\u0639 \u062e\u0631\u06cc\u062f'}
                    sortKey="lifetimeSpend"
                    activeKey={sort.key}
                    direction={sort.direction}
                    onSort={onSort}
                    numeric
                  />
                  <SortableHead
                    label={'\u0645\u0648\u062c\u0648\u062f\u06cc'}
                    sortKey="walletBalance"
                    activeKey={sort.key}
                    direction={sort.direction}
                    onSort={onSort}
                    numeric
                  />
                  <SortableHead
                    label={'\u0639\u0636\u0648\u06cc\u062a'}
                    sortKey="createdAt"
                    activeKey={sort.key}
                    direction={sort.direction}
                    onSort={onSort}
                  />
                </TableRow>
              </TableHeader>

              <TableBody>
                {data.items.map((user) => {
                  const stateMeta = USER_STATE[user.state]
                  return (
                    <TableRow key={user.id}>
                      <TableCell>
                        <Link href={'/users/' + user.id} className="text-primary hover:underline">
                          {truncate(user.displayNameFa, 26)}
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
                        <span className="text-2xs">
                          {user.tierEmoji} {user.tierLabelFa}
                        </span>
                      </TableCell>

                      <TableCell numeric>{faNumber(user.activeSubscriptions)}</TableCell>
                      <TableCell numeric>{toman(user.lifetimeSpend, false)}</TableCell>
                      <TableCell numeric>{toman(user.walletBalance, false)}</TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {faDate(user.createdAt)}
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
