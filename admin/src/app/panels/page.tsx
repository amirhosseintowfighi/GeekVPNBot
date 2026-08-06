'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Plus, RefreshCw, Wifi } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { faNumber, faRelative } from '@/lib/fa'
import { SERVER_HEALTH } from '@/lib/labels'
import type { PanelKind, PanelRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { SkeletonTable } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const PANEL_KIND_LABEL: Record<PanelKind, string> = {
  xui: 'X-UI',
  marzban: 'Marzban',
  marzneshin: 'Marzneshin',
  hiddify: 'Hiddify',
}

/**
 * Panels.
 *
 * A panel is the thing that actually creates the customer's account, so when
 * one is unreachable, provisioning silently fails and paid orders pile up.
 * That is why the sidebar carries an `unhealthyPanels` badge and why this
 * screen leads with health rather than configuration.
 *
 * Test and sync are separate actions on purpose:
 * - Test only proves credentials and reachability. It is read-only and safe.
 * - Sync writes: it reconciles subscriptions against the panel. It is the
 *   slower, riskier button, so its result is reported explicitly instead of
 *   being swallowed by a toast.
 */
export default function PanelsPage() {
  const { can } = useSession()
  const [busyId, setBusyId] = React.useState<string | null>(null)
  const [result, setResult] = React.useState<{ ok: boolean; messageFa: string } | null>(null)

  const { data, error, isLoading, mutate } = useSWR<PanelRow[]>('panels', () => api.panels())

  if (!can('panels.view')) return <ForbiddenState permission="panels.view" />

  const run = async (panel: PanelRow, kind: 'test' | 'sync') => {
    setBusyId(panel.id)
    setResult(null)
    try {
      const response = kind === 'test' ? await api.testPanel(panel.id) : await api.syncPanel(panel.id)
      setResult({ ok: kind === 'sync' ? true : Boolean(response.ok), messageFa: response.messageFa })
    } catch (thrown) {
      setResult({ ok: false, messageFa: thrown instanceof ApiError ? thrown.messageFa : '' })
    } finally {
      setBusyId(null)
      mutate()
    }
  }

  return (
    <>
      <PageHeader
        title={'\u067e\u0646\u0644\u200c\u0647\u0627'}
        description={'\u067e\u0646\u0644\u200c\u0647\u0627\u06cc \u062a\u062d\u0648\u06cc\u0644 \u0627\u0634\u062a\u0631\u0627\u06a9 \u0648 \u0648\u0636\u0639\u06cc\u062a \u0633\u0644\u0627\u0645\u062a \u0622\u0646\u200c\u0647\u0627'}
        actions={
          can('panels.edit') ? (
            <Button>
              <Plus className="size-3.5" aria-hidden />
              {'\u067e\u0646\u0644 \u062c\u062f\u06cc\u062f'}
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

      {result ? (
        <div
          className={
            'rounded-md border px-3 py-2 text-2xs ' +
            (result.ok
              ? 'border-success/30 bg-success/10 text-success'
              : 'border-destructive/30 bg-destructive/10 text-destructive')
          }
        >
          {result.messageFa}
        </div>
      ) : null}

      <Card>
        {isLoading && !data ? (
          <SkeletonTable rows={5} cols={6} />
        ) : !data || data.length === 0 ? (
          <EmptyState
            title={'\u067e\u0646\u0644\u06cc \u062b\u0628\u062a \u0646\u0634\u062f\u0647'}
            description={'\u0628\u062f\u0648\u0646 \u067e\u0646\u0644\u060c \u0633\u0641\u0627\u0631\u0634\u200c\u0647\u0627\u06cc \u062a\u0623\u06cc\u06cc\u062f\u200c\u0634\u062f\u0647 \u062a\u062d\u0648\u06cc\u0644 \u0646\u0645\u06cc\u200c\u0634\u0648\u0646\u062f.'}
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{'\u0646\u0627\u0645'}</TableHead>
                <TableHead>{'\u0646\u0648\u0639'}</TableHead>
                <TableHead>{'\u0622\u062f\u0631\u0633'}</TableHead>
                <TableHead>{'\u0633\u0644\u0627\u0645\u062a'}</TableHead>
                <TableHead>{'\u06a9\u0627\u0631\u0628\u0631\u0627\u0646'}</TableHead>
                <TableHead>{'\u0622\u062e\u0631\u06cc\u0646 \u0647\u0645\u06af\u0627\u0645\u200c\u0633\u0627\u0632\u06cc'}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((panel) => {
                const health = SERVER_HEALTH[panel.health]
                return (
                  <TableRow key={panel.id}>
                    <TableCell>{panel.nameFa}</TableCell>
                    <TableCell className="text-muted-foreground">
                      <span dir="ltr">{PANEL_KIND_LABEL[panel.kind]}</span>
                    </TableCell>
                    <TableCell>
                      <span dir="ltr" className="font-mono text-2xs text-muted-foreground">
                        {panel.baseUrl}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge variant={health.tone} dot>
                        {health.fa}
                      </Badge>
                    </TableCell>
                    <TableCell numeric>{faNumber(panel.userCount)}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {panel.lastSyncAt ? faRelative(panel.lastSyncAt) : '\u0647\u0631\u06af\u0632'}
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        {can('panels.test') ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            loading={busyId === panel.id}
                            onClick={() => run(panel, 'test')}
                          >
                            <Wifi className="size-3.5" aria-hidden />
                            {'\u062a\u0633\u062a'}
                          </Button>
                        ) : null}

                        {can('panels.edit') ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            loading={busyId === panel.id}
                            onClick={() => run(panel, 'sync')}
                          >
                            <RefreshCw className="size-3.5" aria-hidden />
                            {'\u0647\u0645\u06af\u0627\u0645\u200c\u0633\u0627\u0632\u06cc'}
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </Card>
    </>
  )
}
