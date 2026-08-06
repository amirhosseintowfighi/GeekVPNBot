'use client'

import * as React from 'react'
import * as SeparatorPrimitive from '@radix-ui/react-separator'
import * as ProgressPrimitive from '@radix-ui/react-progress'
import * as CheckboxPrimitive from '@radix-ui/react-checkbox'
import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import { Check } from 'lucide-react'

import { cn } from '@/lib/utils'

/**
 * Four small primitives that would otherwise be four files of boilerplate.
 * They are grouped because none of them carries a non-obvious decision except
 * the two documented below.
 */

// ------------------------------------------------------------------ separator

const Separator = React.forwardRef<
  React.ElementRef<typeof SeparatorPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SeparatorPrimitive.Root>
>(({ className, orientation = 'horizontal', decorative = true, ...props }, ref) => (
  <SeparatorPrimitive.Root
    ref={ref}
    decorative={decorative}
    orientation={orientation}
    className={cn(
      'shrink-0 bg-border',
      orientation === 'horizontal' ? 'h-px w-full' : 'h-full w-px',
      className,
    )}
    {...props}
  />
))
Separator.displayName = 'Separator'

// ------------------------------------------------------------------- progress

export type ProgressTone = 'brand' | 'success' | 'warning' | 'destructive'

const TONE_CLASS: Record<ProgressTone, string> = {
  brand: 'bg-primary',
  success: 'bg-success',
  warning: 'bg-warning',
  destructive: 'bg-destructive',
}

const Progress = React.forwardRef<
  React.ElementRef<typeof ProgressPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> & { tone?: ProgressTone }
>(({ className, value, tone = 'brand', ...props }, ref) => {
  const pct = Math.min(100, Math.max(0, value ?? 0))

  return (
    <ProgressPrimitive.Root
      ref={ref}
      value={pct}
      className={cn('relative h-1.5 w-full overflow-hidden rounded-full bg-muted', className)}
      {...props}
    >
      {/*
        The bar fills from the RIGHT, because that is where reading starts
        here. The indicator is full width and translated out to the right by
        the unfilled remainder - a positive translateX in an RTL container
        moves toward the start of the line. Animating transform rather than
        width also keeps the work on the compositor.
      */}
      <ProgressPrimitive.Indicator
        className={cn('h-full w-full transition-transform duration-300', TONE_CLASS[tone])}
        style={{ transform: `translateX(${100 - pct}%)` }}
      />
    </ProgressPrimitive.Root>
  )
})
Progress.displayName = 'Progress'

/**
 * Usage colour thresholds, pinned to the bot's quota-warning thresholds.
 *
 * If these drift, the bar turns amber on a different day than the
 * notification fires, and the two surfaces start telling different stories.
 */
export function usageTone(fraction: number): ProgressTone {
  if (fraction >= 0.9) return 'destructive'
  if (fraction >= 0.75) return 'warning'
  return 'brand'
}

// ------------------------------------------------------------------ checkbox

const Checkbox = React.forwardRef<
  React.ElementRef<typeof CheckboxPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(({ className, ...props }, ref) => (
  <CheckboxPrimitive.Root
    ref={ref}
    className={cn(
      'peer size-4 shrink-0 rounded-sm border border-input',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
      'data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground',
      className,
    )}
    {...props}
  >
    <CheckboxPrimitive.Indicator className="flex items-center justify-center text-current">
      <Check className="size-3" />
    </CheckboxPrimitive.Indicator>
  </CheckboxPrimitive.Root>
))
Checkbox.displayName = 'Checkbox'

// ------------------------------------------------------------------- tooltip

const TooltipProvider = TooltipPrimitive.Provider
const TooltipRoot = TooltipPrimitive.Root
const TooltipTrigger = TooltipPrimitive.Trigger

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 6, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        'z-50 max-w-xs rounded-md border border-border bg-popover px-2.5 py-1.5 text-2xs text-popover-foreground shadow-xl',
        className,
      )}
      {...props}
    />
  </TooltipPrimitive.Portal>
))
TooltipContent.displayName = 'TooltipContent'

/** Shorthand for the common case: an icon button that needs a label. */
export function Tooltip({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <TooltipRoot>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </TooltipRoot>
  )
}

export {
  Separator,
  Progress,
  Checkbox,
  TooltipProvider,
  TooltipRoot,
  TooltipTrigger,
  TooltipContent,
}
