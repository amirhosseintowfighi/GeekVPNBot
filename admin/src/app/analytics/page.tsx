'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Download } from 'lucide-react'

import { api, ApiError, BASE_URL } from '@/lib/api'
import { faNumber, percent, toman } from '@/lib/fa'
import type { AnalyticsBundle } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader } from '@/components/shell/page-header'
import { ErrorState, ForbiddenState } from '@/components/shell/states'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { SkeletonCards, SkeletonChart } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { BreakdownChart, CHART_COLORS, DonutChart, SeriesChart } from '@/components/charts/chart'
import { MetricCardView } from '@/components/feature/metric-card'

const RANGES = [
  { value: '7', labelFa: '\u06f7 \u0631\u0648\u0632' },
  { value: '30', labelFa: '\u06f3\u06f0 \u0631\u0648\u0632' },
  { value: '90', labelFa: '\u06f9\u06f0 \u0631\u0648\u0632' },
  { value: '365', labelFa: '\u06cc\u06a9 \u0633\u0627\u0644' },
] as const

/**
 * Analytics.
 *
 * The dashboard answers "what needs me now"; this screen answers "how is the
 * business doing". Same components, different question, so the action queue
 * is deliberately absent here.
 *
 * Export is a separate permission (`analytics.export`) because a CSV of
 * revenue leaves the building in a way an on-screen chart does not.
 */
export default function AnalyticsPage() {
  const [days, setDays] = React.useState('30')
  const { can } = useSession()

  const { data, error, isLoading } = useSWR<AnalyticsBundle>(
    ['analytics', days],
    () => api.analytics(Number(days)),
  )

  if (!can('analytics.view')) return <ForbiddenState permission="analytics.view" />

  return (
    <>
      <PageHeader
        title={'\u062a\u062d\u0644\u06cc\u0644\u200c\u0647\u0627'}
        description={'\u0631\u0648\u0646\u062f \u062f\u0631\u0622\u0645\u062f\u060c \u0631\u0634\u062f \u0648 \u0631\u06cc\u0632\u0634'}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Tabs value={days} onValueChange={setDays}>
              <TabsList>
                {RANGES.map((range) => (
                  <TabsTrigger key={range.value} value={range.value}>
                    {range.labelFa}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>

            {can('analytics.export') ? (
              <Button variant="outline" size="sm" asChild>
                {/* A real browser navigation, not an SWR cache key like the
                    ones elsewhere in this app - so it has to be the registered
                    path. `/api/admin/...` is not one; nothing serves it. */}
                <a href={BASE_URL + '/api/v1/admin/analytics/export?days=' + days} download>
                  <Download className="size-3.5" aria-hidden />
                  {'\u062e\u0631\u0648\u062c\u06cc CSV'}
                </a>
              </Button>
            ) : null}
          </div>
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
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {data.metrics.map((metric) => (
              <MetricCardView key={metric.key} metric={metric} invert={metric.key === 'churn'} />
            ))}
          </div>

          <div className="grid gap-3 xl:grid-cols-2">
            {/* Both series are nullable in the payload - a range with no data
                at all yields null rather than an empty chart. */}
            {data.revenueSeries ? (
              <Card>
                <CardHeader>
                  <CardTitle>{data.revenueSeries.labelFa}</CardTitle>
                </CardHeader>
                <CardContent className="p-2">
                  <SeriesChart series={data.revenueSeries} color={CHART_COLORS[0]} />
                </CardContent>
              </Card>
            ) : null}

            {data.ordersSeries ? (
              <Card>
                <CardHeader>
                  <CardTitle>{data.ordersSeries.labelFa}</CardTitle>
                </CardHeader>
                <CardContent className="p-2">
                  <SeriesChart series={data.ordersSeries} color={CHART_COLORS[4]} />
                </CardContent>
              </Card>
            ) : null}
          </div>

          <div className="grid gap-3 xl:grid-cols-2">
            {data.methodBreakdown ? (
              <Card>
                <CardHeader>
                  <CardTitle>{data.methodBreakdown.labelFa}</CardTitle>
                </CardHeader>
                <CardContent>
                  <DonutChart slices={data.methodBreakdown.slices} format="toman" />
                </CardContent>
              </Card>
            ) : null}

            {data.planBreakdown ? (
              <Card>
                <CardHeader>
                  <CardTitle>{data.planBreakdown.labelFa}</CardTitle>
                </CardHeader>
                <CardContent>
                  <DonutChart slices={data.planBreakdown.slices} format="toman" />
                </CardContent>
              </Card>
            ) : null}
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{'پرفروش‌ترین پلن‌ها'}</CardTitle>
            </CardHeader>
            <CardContent className="p-2">
              <BreakdownChart
                slices={data.topPlans.map((plan) => ({
                  key: plan.planId,
                  labelFa: plan.planName,
                  value: plan.revenue,
                  share: 0,
                }))}
                format="toman"
                height={260}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{'اثر کمپین‌ها'}</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{'کمپین'}</TableHead>
                    <TableHead>{'دفعات استفاده'}</TableHead>
                    <TableHead>{'تخفیف داده‌شده'}</TableHead>
                    <TableHead>{'درآمد خالص'}</TableHead>
                    <TableHead>{'نرخ استفاده'}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.campaigns.map((row) => (
                    <TableRow key={row.campaignId}>
                      <TableCell>{row.nameFa}</TableCell>
                      <TableCell numeric>{faNumber(row.redemptions)}</TableCell>
                      {/* Discount given is a cost, shown in amber, not red:
                          it is intended spend, not an incident. */}
                      <TableCell numeric className="text-warning">{toman(row.discountGiven, false)}</TableCell>
                      <TableCell numeric>{toman(row.netRevenue, false)}</TableCell>
                      <TableCell numeric>{percent(row.redemptionRate)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      ) : null}

    </>
  )
}
