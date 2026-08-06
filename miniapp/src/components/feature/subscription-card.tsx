'use client'

import * as React from 'react'
import Link from 'next/link'
import { Copy, RefreshCw, Smartphone } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Progress, usageTone } from '@/components/ui/progress'
import {
  countdown,
  faDate,
  faNumber,
  gib,
  usageFraction,
} from '@/lib/fa'
import { copyText, haptic } from '@/lib/telegram'
import type { SubscriptionCard as SubscriptionModel } from '@/lib/types'

/**
 * State copy and colour live together so the two can never drift apart.
 *
 * Green means settled, amber means waiting on us, red means the customer has
 * to act. `suspended` is red because it is the only state a renewal will not
 * fix - the bot's `is_renewable` excludes it, and offering a renew button
 * there would take money for a service that stays off.
 */
const STATE_META = {
  active: { labelFa: '\u0641\u0639\u0627\u0644', variant: 'success' },
  expiring: { labelFa: '\u0631\u0648 \u0628\u0647 \u0627\u062a\u0645\u0627\u0645', variant: 'warning' },
  expired: { labelFa: '\u0645\u0646\u0642\u0636\u06cc \u0634\u062f\u0647', variant: 'destructive' },
  exhausted: { labelFa: '\u062d\u062c\u0645 \u062a\u0645\u0627\u0645 \u0634\u062f\u0647', variant: 'destructive' },
  suspended: { labelFa: '\u062a\u0639\u0644\u06cc\u0642 \u0634\u062f\u0647', variant: 'destructive' },
  pending: { labelFa: '\u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631', variant: 'muted' },
} as const

/** Mirrors `SubscriptionCard.is_renewable` in the bot's read models. */
function isRenewable(state: SubscriptionModel['state']): boolean {
  return (
    state === 'active' ||
    state === 'expiring' ||
    state === 'expired' ||
    state === 'exhausted'
  )
}

export function SubscriptionCardView({
  sub,
  onRotate,
  rotating,
}: {
  sub: SubscriptionModel
  onRotate?: (id: string) => void
  rotating?: boolean
}) {
  const [copied, setCopied] = React.useState(false)
  const meta = STATE_META[sub.state]
  const unlimited = sub.quotaGib === null
  const fraction = unlimited ? 0 : usageFraction(sub.usedGib, sub.quotaGib)

  const handleCopy = async () => {
    if (!sub.subscriptionUrl) return
    haptic.impact('light')
    await copyText(sub.subscriptionUrl)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }

  return (
    <Card className="space-y-4 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{sub.productNameFa}</p>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {sub.planNameFa}
          </p>
        </div>
        <Badge variant={meta.variant} className="shrink-0">
          {meta.labelFa}
        </Badge>
      </div>

      {unlimited ? (
        <p className="text-xs text-muted-foreground">
          {'\u062d\u062c\u0645 \u0645\u0635\u0631\u0641\u06cc: \u0646\u0627\u0645\u062d\u062f\u0648\u062f'}
        </p>
      ) : (
        <div className="space-y-1.5">
          <Progress value={fraction * 100} tone={usageTone(fraction)} />
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span className="nums">
              {`${gib(sub.usedGib)} \u0627\u0632 ${gib(sub.quotaGib)}`}
            </span>
            <span className="nums">
              {`${gib(Math.max(0, (sub.quotaGib ?? 0) - sub.usedGib))} \u0628\u0627\u0642\u06cc\u200c\u0645\u0627\u0646\u062f\u0647`}
            </span>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg bg-secondary/40 px-3 py-2">
          <p className="text-muted-foreground">{'\u0627\u0646\u0642\u0636\u0627'}</p>
          <p className="nums mt-0.5 font-medium">
            {sub.expiresAt
              ? `${faDate(sub.expiresAt)} \u00b7 ${countdown(sub.expiresAt)}`
              : '\u2014'}
          </p>
        </div>
        <div className="rounded-lg bg-secondary/40 px-3 py-2">
          <p className="flex items-center gap-1 text-muted-foreground">
            <Smartphone className="size-3" aria-hidden />
            {'\u062f\u0633\u062a\u06af\u0627\u0647'}
          </p>
          <p className="nums mt-0.5 font-medium">{faNumber(sub.deviceLimit)}</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {sub.subscriptionUrl ? (
          <Button
            variant="outline"
            size="sm"
            onClick={handleCopy}
            className="flex-1"
          >
            <Copy className="size-4" aria-hidden />
            {copied
              ? '\u06a9\u067e\u06cc \u0634\u062f'
              : '\u06a9\u067e\u06cc \u0644\u06cc\u0646\u06a9'}
          </Button>
        ) : null}

        {onRotate ? (
          <Button
            variant="ghost"
            size="sm"
            loading={rotating}
            onClick={() => {
              haptic.impact('medium')
              onRotate(sub.subscriptionId)
            }}
          >
            <RefreshCw className="size-4" aria-hidden />
            {'\u062a\u0639\u0648\u06cc\u0636 \u0644\u06cc\u0646\u06a9'}
          </Button>
        ) : null}

        {isRenewable(sub.state) ? (
          <Button size="sm" asChild className="flex-1">
            <Link href={`/services/${sub.subscriptionId}/renew`}>
              {'\u062a\u0645\u062f\u06cc\u062f'}
            </Link>
          </Button>
        ) : null}
      </div>
    </Card>
  )
}
