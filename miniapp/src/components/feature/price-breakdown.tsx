'use client'

import * as React from 'react'
import { Gift, Info } from 'lucide-react'

import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'
import { toman } from '@/lib/fa'
import type { Quote } from '@/lib/types'

/**
 * The itemised price.
 *
 * The single most important rule in this component: cashback is rendered
 * *below* the total, visually detached, and never folded into the arithmetic.
 * The backend deliberately discloses `cashbackAmount` without subtracting it,
 * because the money arrives in the wallet after the order settles. Showing it
 * as a discount line would produce a total that does not match the amount
 * actually charged, and card-to-card customers transfer that number by hand.
 */
export function PriceBreakdown({
  quote,
  className,
}: {
  quote: Quote
  className?: string
}) {
  // `total` arrives as a line too, but it is rendered separately below so the
  // eye lands on it last.
  const lines = quote.lines.filter(
    (line) => line.kind !== 'total' && line.kind !== 'cashback',
  )

  return (
    <div className={cn('space-y-3', className)}>
      <ul className="space-y-2 text-sm">
        {lines.map((line, index) => {
          const isDiscount = line.amount < 0
          return (
            <li
              key={`${line.kind}-${index}`}
              className="flex items-center justify-between gap-3"
            >
              <span className="min-w-0 truncate text-muted-foreground">
                {line.labelFa}
              </span>
              <span
                className={cn(
                  'nums shrink-0 tabular-nums',
                  isDiscount ? 'text-success' : 'text-foreground',
                )}
              >
                {toman(Math.abs(line.amount), false)}
              </span>
            </li>
          )
        })}
      </ul>

      <Separator />

      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium">
          {'\u0645\u0628\u0644\u063a \u0642\u0627\u0628\u0644 \u067e\u0631\u062f\u0627\u062e\u062a'}
        </span>
        <span className="nums text-lg font-bold">{toman(quote.total)}</span>
      </div>

      {quote.cashbackAmount > 0 ? (
        <div className="flex items-start gap-2 rounded-lg border border-success/25 bg-success/10 px-3 py-2">
          <Gift className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
          <p className="text-xs leading-loose text-success">
            {`\u067e\u0633 \u0627\u0632 \u062a\u0623\u06cc\u06cc\u062f \u067e\u0631\u062f\u0627\u062e\u062a\u060c ${toman(quote.cashbackAmount)} \u0628\u0647 \u06a9\u06cc\u0641 \u067e\u0648\u0644 \u0634\u0645\u0627 \u0628\u0627\u0632\u0645\u06cc\u200c\u06af\u0631\u062f\u062f. \u0627\u06cc\u0646 \u0645\u0628\u0644\u063a \u0627\u0632 \u0645\u0628\u0644\u063a \u0627\u0645\u0631\u0648\u0632 \u06a9\u0633\u0631 \u0646\u0645\u06cc\u200c\u0634\u0648\u062f.`}
          </p>
        </div>
      ) : null}

      {quote.campaignNameFa ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Info className="size-3.5 shrink-0" aria-hidden />
          {`\u06a9\u0645\u067e\u06cc\u0646 \u0641\u0639\u0627\u0644: ${quote.campaignNameFa}`}
        </p>
      ) : null}
    </div>
  )
}
