'use client'

import * as React from 'react'
import useSWR from 'swr'

import { BreakdownChart, CHART_COLORS, SeriesChart } from '@/components/charts/chart'
import { ErrorState } from '@/components/shell/states'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError, api } from '@/lib/api'
import { faNumber, toman } from '@/lib/fa'
import type { ResellerAnalytics } from '@/lib/types'

const PERIODS = [
  { days: 7, label: '۷ روز' },
  { days: 30, label: '۳۰ روز' },
  { days: 90, label: '۹۰ روز' },
] as const

/**
 * A reseller's trade over time.
 *
 * The portal had four all-time sums and no way to see whether this week beat
 * last, which packages sell, or whether the bot still brings people in. These
 * are the platform dashboard's charts, cut to their own rows on the server.
 */
export function ResellerCharts() {
  const [days, setDays] = React.useState<number>(30)
  const { data, error, mutate } = useSWR<ResellerAnalytics>(['reseller-analytics', days], () =>
    api.myAnalytics(days),
  )

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium">نمودار فروش</h2>
        <div className="flex gap-1" role="radiogroup" aria-label="بازهٔ نمودار">
          {PERIODS.map((period) => (
            <Button
              key={period.days}
              size="sm"
              role="radio"
              aria-checked={days === period.days}
              variant={days === period.days ? 'default' : 'outline'}
              onClick={() => setDays(period.days)}
            >
              {period.label}
            </Button>
          ))}
        </div>
      </div>

      {error ? (
        <ErrorState
          messageFa={error instanceof ApiError ? error.messageFa : 'نمودارها بارگذاری نشد.'}
          onRetry={() => void mutate()}
        />
      ) : !data ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat label="فروش در این بازه" value={faNumber(data.sales.total)} />
            <Stat label="پرداخت مشتری‌ها در ربات" value={toman(data.revenue.total)} />
            <Stat label="هزینهٔ خرید از ما" value={toman(data.cost.total)} />
            <Stat
              label="مشتری جدید / کل"
              value={`${faNumber(data.newCustomers)} / ${faNumber(data.customers)}`}
              hint={`${faNumber(data.activeServices)} سرویس فعال`}
            />
          </div>

          <div className="grid gap-3 xl:grid-cols-2">
            <ChartCard title={data.sales.labelFa}>
              <SeriesChart series={data.sales} color={CHART_COLORS[4]} />
            </ChartCard>
            <ChartCard title={data.revenue.labelFa}>
              <SeriesChart series={data.revenue} color={CHART_COLORS[0]} />
            </ChartCard>
            <ChartCard title={data.cost.labelFa}>
              <SeriesChart series={data.cost} color={CHART_COLORS[2]} />
            </ChartCard>
            <ChartCard title="پرفروش‌ترین پلن‌ها">
              {data.topPlans.length ? (
                <BreakdownChart slices={data.topPlans} />
              ) : (
                <p className="py-10 text-center text-sm text-muted-foreground">
                  در این بازه فروشی در ربات نبوده.
                </p>
              )}
            </ChartCard>
          </div>
        </>
      )}
    </section>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
      {hint ? <div className="mt-0.5 text-2xs text-muted-foreground">{hint}</div> : null}
    </Card>
  )
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}
