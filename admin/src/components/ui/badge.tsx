import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

/**
 * Status pills.
 *
 * The tone vocabulary is shared with the bot and the Mini App on purpose:
 * green means settled, amber means waiting on us, red means someone must act.
 * An operator and a customer looking at the same order must not read two
 * different stories from the colour.
 *
 * All variants are tinted rather than solid, because a table with thirty rows
 * of solid pills is unreadable.
 */
const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs font-medium whitespace-nowrap',
  {
    variants: {
      variant: {
        default: 'border-primary/30 bg-primary/15 text-primary',
        success: 'border-success/30 bg-success/15 text-success',
        warning: 'border-warning/30 bg-warning/15 text-warning',
        destructive: 'border-destructive/30 bg-destructive/15 text-destructive',
        info: 'border-info/30 bg-info/15 text-info',
        muted: 'border-border bg-muted text-muted-foreground',
        outline: 'border-border bg-transparent text-foreground',
      },
    },
    defaultVariants: { variant: 'muted' },
  },
)

export type BadgeTone = NonNullable<VariantProps<typeof badgeVariants>['variant']>

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {
  /** Renders a small filled dot before the label, for state columns. */
  dot?: boolean
}

function Badge({ className, variant, dot = false, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props}>
      {dot ? <span className="size-1.5 rounded-full bg-current" aria-hidden /> : null}
      {children}
    </span>
  )
}

export { Badge, badgeVariants }
