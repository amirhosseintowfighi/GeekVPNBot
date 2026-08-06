import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

/**
 * Small status and marketing labels.
 *
 * The semantic variants map to the subscription and payment states, so the
 * same colour always means the same thing across the app: green settled,
 * amber waiting on someone, red needs action.
 */
const badgeVariants = cva(
  cn(
    'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5',
    'text-xs font-medium leading-5 transition-colors',
  ),
  {
    variants: {
      variant: {
        default: 'border-transparent bg-secondary text-secondary-foreground',
        brand:
          'border-transparent bg-brand-gradient text-primary-foreground shadow shadow-primary/25',
        outline: 'border-border text-foreground',
        success: 'border-transparent bg-success/15 text-success',
        warning: 'border-transparent bg-warning/15 text-warning',
        destructive: 'border-transparent bg-destructive/15 text-destructive',
        muted: 'border-transparent bg-muted text-muted-foreground',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
