'use client'

import useSWR from 'swr'
import { Server } from 'lucide-react'

import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Progress, usageTone } from '@/components/ui/progress'
import { SkeletonList } from '@/components/ui/skeleton'
import { ApiError, fetcher } from '@/lib/api'
import { faNumber, percent } from '@/lib/fa'
import type { ServerHealth, ServerStatusRow } from '@/lib/types'

const HEALTH_META: Record<
  ServerHealth,
  { labelFa: string; variant: 'success' | 'warning' | 'destructive' | 'muted' }
> = {
  healthy: { labelFa: '\u0633\u0627\u0644\u0645', variant: 'success' },
  degraded: { labelFa: '\u06a9\u0646\u062f', variant: 'warning' },
  down: { labelFa: '\u062e\u0627\u0631\u062c \u0627\u0632 \u062f\u0633\u062a\u0631\u0633', variant: 'destructive' },
  maintenance: { labelFa: '\u062f\u0631 \u062d\u0627\u0644 \u062a\u0639\u0645\u06cc\u0631', variant: 'muted' },
}

/**
 * Server status.
 *
 * Refreshed on an interval because this is the screen someone opens *while*
 * something is broken, and a stale "healthy" here sends them to support for a
 * problem we already know about.
 *
 * Load reuses the subscription usage tone scale, so an amber bar means the
 * same thing on both screens.
 */
export default function StatusPage() {
  const { data, error, mutate } = useSWR<ServerStatusRow[]>(
    '/api/miniapp/servers',
    fetcher,
    { refreshInterval: 60_000 },
  )

  return (
    <>
      <PageHeader
        title={'\u0648\u0636\u0639\u06cc\u062a \u0633\u0631\u0648\u0631\u0647\u0627'}
        subtitle={'\u0647\u0631 \u06cc\u06a9 \u062f\u0642\u06cc\u0642\u0647 \u0628\u0647\u200c\u0631\u0648\u0632 \u0645\u06cc\u200c\u0634\u0648\u062f'}
      />

      {error instanceof ApiError && !data ? (
        <ErrorState
          messageFa={error.messageFa}
          offline={error.status === 0}
          onRetry={() => void mutate()}
        />
      ) : !data ? (
        <SkeletonList count={4} />
      ) : data.length === 0 ? (
        <EmptyState
          icon={Server}
          title={'\u0627\u0637\u0644\u0627\u0639\u0627\u062a\u06cc \u062f\u0631 \u062f\u0633\u062a\u0631\u0633 \u0646\u06cc\u0633\u062a'}
        />
      ) : (
        <ul className="space-y-2 pb-4">
          {data.map((row) => {
            const meta = HEALTH_META[row.health]
            const fraction =
              row.loadPercent === null ? null : Math.min(1, Math.max(0, row.loadPercent / 100))

            return (
              <li key={row.nameFa}>
                <Card className="space-y-2.5 p-3.5">
                  <div className="flex items-center justify-between gap-3">
                    <p className="min-w-0 truncate text-sm font-medium">
                      {row.nameFa}
                    </p>
                    <Badge variant={meta.variant} className="shrink-0">
                      {meta.labelFa}
                    </Badge>
                  </div>

                  {fraction !== null ? (
                    <div className="space-y-1">
                      <Progress value={fraction * 100} tone={usageTone(fraction)} />
                      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                        <span>{'\u0628\u0627\u0631 \u0633\u0631\u0648\u0631'}</span>
                        <span className="nums">{percent(row.loadPercent!)}</span>
                      </div>
                    </div>
                  ) : null}

                  {row.latencyMs !== null ? (
                    <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                      <span>{'\u062a\u0627\u062e\u06cc\u0631'}</span>
                      <span className="nums">
                        {faNumber(row.latencyMs) + ' \u0645\u06cc\u0644\u06cc\u200c\u062b\u0627\u0646\u06cc\u0647'}
                      </span>
                    </div>
                  ) : null}
                </Card>
              </li>
            )
          })}
        </ul>
      )}
    </>
  )
}
