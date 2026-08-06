'use client'

import * as React from 'react'
import * as ProgressPrimitive from '@radix-ui/react-progress'

import { cn } from '@/lib/utils'

/**
 * The traffic-usage bar.
 *
 * The fill is translated rather than width-animated, because transform is
 * compositor-only and stays smooth on the low-end Android devices that make up
 * a large share of the audience.
 *
 * Note the RTL handling: the track fills from the right, matching the reading
 * direction. Radix's default translate assumes LTR, so the sign is flipped.
 *
 * `tone` exists because a usage bar means the opposite of a progress bar - at
 * 95% the customer is nearly out of traffic, which is bad news and should not
 * be painted in the brand gradient.
 */
const Progress = React.forwardRef<
  React.ElementRef<typeof ProgressPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> & {
    tone?: 'brand' | 'success' | 'warning' | 'destructive'
  }
>(({ className, value, tone = 'brand', ...props }, ref) => {
  const pct = Math.min(100, Math.max(0, value ?? 0))

  return (
    <ProgressPrimitive.Root
      ref={ref}
      value={pct}
      className={cn(
        'relative h-2 w-full overflow-hidden rounded-full bg-muted',
        className,
      )}
      {...props}
    >
      <ProgressPrimitive.Indicator
        className={cn(
          'h-full w-full flex-1 rounded-full transition-transform duration-500 ease-out',
          tone === 'brand' && 'bg-brand-gradient',
          tone === 'success' && 'bg-success',
          tone === 'warning' && 'bg-warning',
          tone === 'destructive' && 'bg-destructive',
        )}
        style={{ transform: `translateX(${100 - pct}%)` }}
      />
    </ProgressPrimitive.Root>
  )
})
Progress.displayName = ProgressPrimitive.Root.displayName

/**
 * Pick a colour from how much traffic is left.
 *
 * Thresholds match the bot's quota-warning notification, so the bar turns
 * amber at the same moment the customer gets the message telling them so.
 */
export function usageTone(
  fraction: number,
): 'brand' | 'warning' | 'destructive' {
  if (fraction >= 0.9) return 'destructive'
  if (fraction >= 0.75) return 'warning'
  return 'brand'
}

export { Progress }
