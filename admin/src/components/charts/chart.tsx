'use client'

import * as React from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { faDate, faNumber, percent } from '@/lib/fa'
import type { BreakdownSlice, MetricCard, TimeSeries } from '@/lib/types'
import { cn } from '@/lib/utils'

/**
 * Charts.
 *
 * Recharts is not RTL-aware, so three things are handled here once instead of
 * at every call site:
 *
 * 1. `reversed` on the X axis. Time must run right-to-left to match how the
 *    rest of the panel is read; a left-to-right timeline in an RTL interface
 *    is read backwards at a glance, and "revenue is falling" is exactly the
 *    kind of misreading that must not happen.
 * 2. `orientation="right"` on the Y axis, so the scale sits at the start of
 *    the reading direction.
 * 3. Every number that reaches a label or a tooltip goes through the shared
 *    Persian formatters. A Latin-digit axis beside Persian-digit table cells
 *    is how an operator ends up comparing two numbers that look unrelated.
 */

/** Categorical palette. Ordered so the first three stay distinguishable for
 *  the most common colour-vision deficiencies. */
export const CHART_COLORS = [
  'hsl(217 91% 60%)',
  'hsl(152 60% 42%)',
  'hsl(38 92% 52%)',
  'hsl(280 65% 60%)',
  'hsl(199 89% 52%)',
  'hsl(0 72% 55%)',
] as const

type Format = MetricCard['format']

export function formatValue(value: number, format: Format): string {
  switch (format) {
    case 'toman':
      // Compacted, like the axis ticks. `compact` existed and did exactly this,
      // and nothing called it from here: a headline card printed the full eight
      // digits while the axis beside it printed a magnitude, so the same figure
      // read two different ways on one screen.
      return compact(value, 'toman') + ' تومان'
    case 'percent':
      return percent(value)
    case 'gib':
      return faNumber(value) + ' \u06af\u06cc\u06af\u0627\u0628\u0627\u06cc\u062a'
    default:
      return faNumber(value)
  }
}

/** Compact axis labels: 1_250_000 becomes ۱٫۲ میلیون. A full toman figure
 *  repeated down an axis eats a third of the plot width. */
function compact(value: number, format: Format): string {
  if (format !== 'toman') return faNumber(value)
  if (Math.abs(value) >= 1_000_000) return faNumber(value / 1_000_000, 1) + ' \u0645\u06cc\u0644\u06cc\u0648\u0646'
  if (Math.abs(value) >= 1_000) return faNumber(value / 1_000) + ' \u0647\u0632\u0627\u0631'
  return faNumber(value)
}

const AXIS_PROPS = {
  stroke: 'hsl(215 14% 62%)',
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const

function ChartTooltip({
  active,
  payload,
  label,
  format,
  labelIsDate = false,
}: {
  active?: boolean
  payload?: Array<{ name?: string; value?: number; color?: string }>
  label?: string | number
  format: Format
  labelIsDate?: boolean
}) {
  if (!active || !payload?.length) return null

  return (
    <div className="rounded-md border border-border bg-popover px-2.5 py-2 text-2xs shadow-xl">
      <p className="mb-1 text-muted-foreground">
        {labelIsDate && label !== undefined ? faDate(String(label)) : String(label ?? '')}
      </p>
      {payload.map((entry, index) => (
        <p key={index} className="nums flex items-center gap-1.5 font-medium">
          <span className="size-2 rounded-full" style={{ background: entry.color }} aria-hidden />
          {formatValue(entry.value ?? 0, format)}
        </p>
      ))}
    </div>
  )
}

/** A single metric over time. */
export function SeriesChart({
  series,
  height = 260,
  color = CHART_COLORS[0],
  className,
}: {
  series: TimeSeries
  height?: number
  color?: string
  className?: string
}) {
  const gradientId = React.useId()

  return (
    <div className={cn('w-full', className)} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={series.points} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.35} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>

          <CartesianGrid strokeDasharray="3 3" stroke="hsl(225 10% 20%)" vertical={false} />

          {/*
            Time runs right-to-left.

            `labelFa`, not `at`: the server already labels each bucket, and it
            labels it for the granularity - a month bucket reads as a month
            rather than as its first day. The axis used `dataKey="date"`, a
            field no point has, so every tick formatted `undefined` and the
            whole axis read "NaN اسفند". A `dataKey` is a string Recharts looks
            up at runtime, so nothing typechecked it.
          */}
          <XAxis dataKey="labelFa" reversed {...AXIS_PROPS} minTickGap={24} />
          <YAxis
            orientation="right"
            {...AXIS_PROPS}
            width={64}
            tickFormatter={(value: number) => compact(value, series.format)}
          />

          {/* The tooltip's label is now the bucket's own Persian text, not
              an ISO date, so re-formatting it would put the NaN back - here
              instead of on the axis. */}
          <Tooltip
            content={<ChartTooltip format={series.format} labelIsDate={false} />}
            cursor={{ stroke: 'hsl(225 10% 30%)' }}
          />

          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={2}
            fill={'url(#' + gradientId + ')'}
            // No dots on a 90-point series - they merge into a smear.
            dot={series.points.length <= 14}
            activeDot={{ r: 3 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

/**
 * A breakdown, drawn as horizontal bars rather than a pie.
 *
 * Pies are hard to compare and worse with Persian labels, which are longer
 * than their English equivalents and collide around the circumference. Bars
 * sort, label cleanly, and answer "which is biggest" instantly.
 */
export function BreakdownChart({
  slices,
  format = 'count',
  height = 220,
  className,
}: {
  slices: BreakdownSlice[]
  format?: Format
  height?: number
  className?: string
}) {
  const data = [...slices].sort((a, b) => b.value - a.value)

  return (
    <div className={cn('w-full', className)} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(225 10% 20%)" horizontal={false} />
          <XAxis type="number" reversed {...AXIS_PROPS} tickFormatter={(v: number) => compact(v, format)} />
          <YAxis
            type="category"
            dataKey="labelFa"
            orientation="right"
            {...AXIS_PROPS}
            width={110}
          />
          <Tooltip
            content={<ChartTooltip format={format} labelIsDate={false} />}
            cursor={{ fill: 'hsl(225 12% 18%)' }}
          />
          <Bar dataKey="value" radius={[0, 4, 4, 0]}>
            {data.map((_, index) => (
              <Cell key={index} fill={CHART_COLORS[index % CHART_COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/** A donut, kept for mixes of three or four parts where share is the point. */
export function DonutChart({
  slices,
  format = 'count',
  height = 220,
  className,
}: {
  slices: BreakdownSlice[]
  format?: Format
  height?: number
  className?: string
}) {
  const total = slices.reduce((sum, slice) => sum + slice.value, 0)

  return (
    <div className={cn('flex flex-wrap items-center gap-4', className)}>
      <div style={{ height, width: height }} className="shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={slices} dataKey="value" nameKey="labelFa" innerRadius="58%" outerRadius="88%" paddingAngle={2}>
              {slices.map((_, index) => (
                <Cell key={index} fill={CHART_COLORS[index % CHART_COLORS.length]} stroke="none" />
              ))}
            </Pie>
            <Tooltip content={<ChartTooltip format={format} labelIsDate={false} />} />
          </PieChart>
        </ResponsiveContainer>
      </div>

      {/* The legend carries the numbers. Reading a share off the arc is
          guesswork; the operator needs the figure. */}
      <ul className="min-w-40 flex-1 space-y-1.5">
        {slices.map((slice, index) => (
          <li key={slice.key} className="flex items-center justify-between gap-2 text-2xs">
            <span className="flex items-center gap-1.5">
              <span
                className="size-2 rounded-full"
                style={{ background: CHART_COLORS[index % CHART_COLORS.length] }}
                aria-hidden
              />
              {slice.labelFa}
            </span>
            <span className="nums text-muted-foreground">
              {formatValue(slice.value, format)}
              {total > 0 ? ' \u00b7 ' + percent((slice.value / total) * 100) : ''}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
