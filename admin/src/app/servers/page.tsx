'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Plus } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { faNumber, faRelative } from '@/lib/fa'
import { SERVER_HEALTH } from '@/lib/labels'
import type { ServerRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { NodeDialog } from '@/components/feature/node-dialog'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { SkeletonTable } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Progress, usageTone } from '@/components/ui/primitives'

/**
 * Servers.
 *
 * The admin-side twin of the customer status page, carrying the numbers
 * customers must never see: load, capacity, latency.
 *
 * `isVisible` controls whether a node appears on the public status page. It
 * is a switch rather than a delete because pulling a server during
 * maintenance must not destroy its history or its bound plans.
 */
export default function ServersPage() {
  const [creating, setCreating] = React.useState(false)
  const { can } = useSession()
  const { data, error, isLoading, mutate } = useSWR<ServerRow[]>('servers', () => api.servers())

  if (!can('panels.read')) return <ForbiddenState permission="panels.read" />

  return (
    <>
      <PageHeader
        title={'\u0633\u0631\u0648\u0631\u0647\u0627'}
        description={'\u0638\u0631\u0641\u06cc\u062a\u060c \u062a\u0623\u062e\u06cc\u0631 \u0648 \u0646\u0645\u0627\u06cc\u0634 \u062f\u0631 \u0635\u0641\u062d\u0647\u0654 \u0648\u0636\u0639\u06cc\u062a'}
        actions={
          can('panels.write') ? (
            <Button onClick={() => setCreating(true)}>
              <Plus className="size-3.5" aria-hidden />
              {'\u0633\u0631\u0648\u0631 \u062c\u062f\u06cc\u062f'}
            </Button>
          ) : null
        }
      />

      {error ? (
        <ErrorState
          messageFa={error instanceof ApiError ? error.messageFa : ''}
          offline={error instanceof ApiError && error.status === 0}
          onRetry={() => mutate()}
        />
      ) : null}

      <Card>
        {isLoading && !data ? (
          <SkeletonTable rows={6} cols={6} />
        ) : !data || data.length === 0 ? (
          <EmptyState title={'\u0633\u0631\u0648\u0631\u06cc \u062b\u0628\u062a \u0646\u0634\u062f\u0647'} />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{'\u0633\u0631\u0648\u0631'}</TableHead>
                <TableHead>{'\u06a9\u0634\u0648\u0631'}</TableHead>
                <TableHead>{'\u0648\u0636\u0639\u06cc\u062a'}</TableHead>
                <TableHead>{'\u0638\u0631\u0641\u06cc\u062a'}</TableHead>
                <TableHead>{'\u0622\u062e\u0631\u06cc\u0646 \u0628\u0631\u0631\u0633\u06cc'}</TableHead>
                <TableHead>{'\u067e\u0630\u06cc\u0631\u0634 \u06a9\u0627\u0631\u0628\u0631 \u062c\u062f\u06cc\u062f'}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((server) => {
                // A node reports capacity and a live account count, not a load
                // percentage or a latency: those were read off a shape this API
                // has never returned, so every cell rendered undefined.
                const health = SERVER_HEALTH[server.state]
                const fraction =
                  server.capacity > 0 ? Math.min(1, server.accountCount / server.capacity) : 0
                return (
                  <TableRow key={server.id}>
                    <TableCell>{server.nameFa}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {server.countryCode ?? '\u2014'}
                    </TableCell>
                    <TableCell>
                      <Badge variant={health.tone} dot>
                        {health.fa}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="min-w-28 space-y-1">
                        {/* Same 75/90 percent thresholds the customer app uses
                            for quota, so "amber means getting full" reads the
                            same everywhere. */}
                        <Progress value={fraction * 100} tone={usageTone(fraction)} />
                        <span className="nums text-2xs text-muted-foreground">
                          {faNumber(server.accountCount) +
                            ' / ' +
                            faNumber(server.capacity)}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {server.lastCheckAt ? faRelative(server.lastCheckAt) : '\u2014'}
                    </TableCell>
                    <TableCell>
                      <Switch
                        checked={server.acceptingNew}
                        disabled={!can('panels.write')}
                        onCheckedChange={async (checked) => {
                          await api.saveServer(server.id, { acceptingNew: checked })
                          mutate()
                        }}
                      />
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </Card>

      <NodeDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={() => mutate()}
      />
    </>
  )
}
