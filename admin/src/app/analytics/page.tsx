'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Download } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
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
                <a href={'/api/admin/analytics/export?days=' + days} download>
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
                <CardTitle>{data.ordersSeries.labelFa}</CardTitle>
              </CardHeader>
              <CardContent className="p-2">
                <SeriesChart series={data.ordersSeries} color={CHART_COLORS[4]} />
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

            <Card>
              <CardHeader>
                <CardTitle>{data.churnSeries.labelFa}</CardTitle>
              </CardHeader>
              <CardContent className="p-2">
                {/* Churn is the one series drawn in red: on this chart, up is bad. */}
                <SeriesChart series={data.churnSeries} color={CHART_COLORS[5]} />
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-3 xl:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>{'\u0633\u0647\u0645 \u0631\u0648\u0634\u200c\u0647\u0627\u06cc \u067e\u0631\u062f\u0627\u062e\u062a'}</CardTitle>
              </CardHeader>
              <CardContent>
                <DonutChart slices={data.methodMix} format="toman" />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>{'\u0633\u0637\u062d \u0648\u0641\u0627\u062f\u0627\u0631\u06cc \u06a9\u0627\u0631\u0628\u0631\u0627\u0646'}</CardTitle>
              </CardHeader>
              <CardContent>
                <DonutChart slices={data.tierMix} format="count" />
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{'\u067e\u0631\u0641\u0631\u0648\u0634\u200c\u062a\u0631\u06cc\u0646 \u0645\u062d\u0635\u0648\u0644\u0627\u062a'}</CardTitle>
            </CardHeader>
            <CardContent className="p-2">
              <BreakdownChart slices={data.topProducts} format="toman" height={260} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{'\u0627\u062b\u0631 \u06a9\u062f\u0647\u0627\u06cc \u062a\u062e\u0641\u06cc\u0641'}</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{'\u06a9\u062f'}</TableHead>
                    <TableHead>{'\u062f\u0641\u0639\u0627\u062a \u0627\u0633\u062a\u0641\u0627\u062f\u0647'}</TableHead>
                    <TableHead>{'\u062a\u062e\u0641\u06cc\u0641 \u062f\u0627\u062f\u0647\u200c\u0634\u062f\u0647'}</TableHead>
                    <TableHead>{'\u062f\u0631\u0622\u0645\u062f \u062d\u0627\u0635\u0644'}</TableHead>
                    <TableHead>{'\u0646\u0631\u062e \u062a\u0628\u062f\u06cc\u0644'}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.couponImpact.map((row) => (
                    <TableRow key={row.code}>
                      <TableCell>
                        <span dir="ltr" className="font-mono text-2xs">{row.code}</span>
                      </TableCell>
                      <TableCell numeric>{faNumber(row.uses)}</TableCell>
                      {/* Discount given is a cost, shown in amber, not red:
                          it is intended spend, not an incident. */}
                      <TableCell numeric className="text-warning">{toman(row.discountGiven, false)}</TableCell>
                      <TableCell numeric>{toman(row.revenue, false)}</TableCell>
                      <TableCell numeric>{percent(row.conversionRate, 1)}</TableCell>
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
