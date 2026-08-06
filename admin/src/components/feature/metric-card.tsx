'use client'

import { TrendingDown, TrendingUp } from 'lucide-react'

import { faNumber, percent } from '@/lib/fa'
import type { MetricCard as MetricCardModel } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Card } from '@/components/ui/card'
import { formatValue } from '@/components/charts/chart'

/**
 * One KPI.
 *
 * The delta is the subtle part. `deltaPercent` is nullable and null means
 * "unknown", usually because there is no comparable prior period. Null renders
 * as nothing at all - never as a grey 0%, which is a claim of stability the
 * data does not support.
 *
 * Direction is not assumed good or bad here either: churn rising is red,
 * revenue rising is green, so the caller passes `invert`.
 */
export function MetricCardView({ metric, invert = false }: { metric: MetricCardModel; invert?: boolean }) {
  const delta = metric.deltaPercent
  const hasDelta = delta !== null && delta !== undefined
  const up = hasDelta && delta > 0
  const flat = hasDelta && delta === 0
  const good = invert ? !up : up

  return (
    <Card className="p-4">
      <p className="text-2xs text-muted-foreground">{metric.labelFa}</p>
      <p className="nums mt-1 text-lg font-semibold">{formatValue(metric.value, metric.format)}</p>

      <div className="mt-1 flex items-center gap-2">
        {hasDelta && !flat ? (
          <span
            className={cn(
              'nums inline-flex items-center gap-1 text-2xs font-medium',
              good ? 'text-success' : 'text-destructive',
            )}
          >
            {up ? <TrendingUp className="size-3" aria-hidden /> : <TrendingDown className="size-3" aria-hidden />}
            {percent(Math.abs(delta), 1)}
          </span>
        ) : null}

        {metric.hintFa ? <span className="truncate text-2xs text-muted-foreground/80">{metric.hintFa}</span> : null}
      </div>
    </Card>
  )
}

/** Compact count used by the action queue. */
export function QueueTile({
  labelFa,
  count,
  href,
  tone,
}: {
  labelFa: string
  count: number
  href: string
  tone: 'warning' | 'destructive' | 'info'
}) {
  const idle = count === 0

  return (
    <a
      href={href}
      className={cn(
        'flex items-center justify-between gap-2 rounded-md border px-3 py-2 transition-colors',
        // An empty queue is deliberately colourless. If every tile glows, the
        // one that actually needs a human stops standing out.
        idle
          ? 'border-border bg-muted/40 text-muted-foreground hover:bg-muted'
          : tone === 'destructive'
            ? 'border-destructive/30 bg-destructive/10 text-destructive hover:bg-destructive/15'
            : tone === 'warning'
              ? 'border-warning/30 bg-warning/10 text-warning hover:bg-warning/15'
              : 'border-info/30 bg-info/10 text-info hover:bg-info/15',
      )}
    >
      <span className="text-2xs font-medium">{labelFa}</span>
      <span className="nums text-sm font-semibold">{faNumber(count)}</span>
    </a>
  )
}
