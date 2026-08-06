'use client'

import * as React from 'react'
import useSWR from 'swr'

import { api, ApiError } from '@/lib/api'
import { faRelative } from '@/lib/fa'
import type { DashboardSummary } from '@/lib/types'
import { PageHeader } from '@/components/shell/page-header'
import { ErrorState } from '@/components/shell/states'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { SkeletonCards, SkeletonChart } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { BreakdownChart, CHART_COLORS, SeriesChart } from '@/components/charts/chart'
import { MetricCardView, QueueTile } from '@/components/feature/metric-card'

const RANGES = [
  { value: '7', labelFa: '\u06f7 \u0631\u0648\u0632' },
  { value: '30', labelFa: '\u06f3\u06f0 \u0631\u0648\u0632' },
  { value: '90', labelFa: '\u06f9\u06f0 \u0631\u0648\u0632' },
] as const

/**
 * The dashboard.
 *
 * Ordered by urgency, not by prettiness. The action queue is first because it
 * is the only block on this screen that represents a person currently
 * waiting: a card-to-card receipt nobody has approved, a ticket nobody has
 * answered, a provision that failed. Charts are context and come after.
 */
export default function DashboardPage() {
  const [days, setDays] = React.useState('30')

  const { data, error, isLoading } = useSWR<DashboardSummary>(
    '/api/admin/dashboard?days=' + days,
    () => api.dashboard(Number(days)),
  )

  return (
    <>
      <PageHeader
        title={'\u062f\u0627\u0634\u0628\u0648\u0631\u062f'}
        description={
          data
            ? '\u0622\u062e\u0631\u06cc\u0646 \u0628\u0647\u200c\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06cc: ' +
              faRelative(data.generatedAt)
            : undefined
        }
        actions={
          <Tabs value={days} onValueChange={setDays}>
            <TabsList>
              {RANGES.map((range) => (
                <TabsTrigger key={range.value} value={range.value}>
                  {range.labelFa}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        }
      />

      {error ? (
        <ErrorState
          messageFa={error instanceof ApiError ? error.messageFa : ''}
          offline={error instanceof ApiError && error.status === 0}
          onRetry={() => window.location.reload()}
        />
      ) : null}

      {isLoading && !data ? (
        <div className="space-y-4">
          <SkeletonCards count={4} />
          <SkeletonChart />
        </div>
      ) : null}

      {data ? (
        <div className="space-y-4">
          {/* --- what needs a human, right now --- */}
          <Card>
            <CardHeader>
              <CardTitle>{'\u0646\u06cc\u0627\u0632\u0645\u0646\u062f \u0631\u0633\u06cc\u062f\u06af\u06cc'}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
              <QueueTile
                labelFa={'\u067e\u0631\u062f\u0627\u062e\u062a \u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 \u062a\u0623\u06cc\u06cc\u062f'}
                count={data.queue.pendingPayments}
                href="/orders?state=pending_review"
                tone="warning"
              />
              <QueueTile
                labelFa={'\u062a\u06cc\u06a9\u062a \u0628\u0627\u0632'}
                count={data.queue.openTickets}
                href="/tickets?state=open"
                tone="info"
              />
              <QueueTile
                labelFa={'\u062a\u062d\u0648\u06cc\u0644 \u0646\u0627\u0645\u0648\u0641\u0642'}
                count={data.queue.failedProvisions}
                href="/logs?level=error"
                tone="destructive"
              />
              <QueueTile
                labelFa={'\u067e\u0646\u0644 \u0645\u0639\u06cc\u0648\u0628'}
                count={data.queue.unhealthyPanels}
                href="/panels"
                tone="destructive"
              />
              <QueueTile
                labelFa={'\u0627\u0646\u0642\u0636\u0627\u06cc \u0627\u0645\u0631\u0648\u0632'}
                count={data.queue.expiringToday}
                href="/users?filter=expiring"
                tone="info"
              />
            </CardContent>
          </Card>

          {/* --- headline numbers --- */}
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {data.metrics.map((metric) => (
              <MetricCardView
                key={metric.key}
                metric={metric}
                // Churn is the one headline metric where up is bad.
                invert={metric.key === 'churn'}
              />
            ))}
          </div>

          {/* --- trends --- */}
          <div className="grid gap-3 xl:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>{data.revenueSeries.labelFa}</CardTitle>
              </CardHeader>
              <CardContent className="p-2">
                <SeriesChart series={data.revenueSeries} color={CHART_COLORS[0]} />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>{data.signupSeries.labelFa}</CardTitle>
              </CardHeader>
              <CardContent className="p-2">
                <SeriesChart series={data.signupSeries} color={CHART_COLORS[1]} />
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{'\u062a\u0631\u06a9\u06cc\u0628 \u0641\u0631\u0648\u0634 \u067e\u0644\u0646\u200c\u0647\u0627'}</CardTitle>
            </CardHeader>
            <CardContent className="p-2">
              <BreakdownChart slices={data.planMix} format="count" />
            </CardContent>
          </Card>
        </div>
      ) : null}
    </>
  )
}
