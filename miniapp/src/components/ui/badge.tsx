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
/**
 * Status chips. Soft fill, darkened `-ink` text so the label passes 4.5:1 -
 * the reference tints alone (green on mint, amber on cream) did not.
 */
const badgeVariants = cva(
  cn(
    'inline-flex h-[26px] items-center gap-1.5 rounded-[9px] border border-transparent px-2.5',
    'text-xs font-extrabold leading-none transition-colors [&_svg]:size-3.5',
  ),
  {
    variants: {
      variant: {
        default: 'bg-[#EAF5FD] text-[#0067AC]',
        brand: 'bg-navy text-white',
        outline: 'border-[color:var(--line)] text-foreground',
        success: 'bg-success-soft text-success-ink',
        warning: 'bg-warning-soft text-warning-ink',
        destructive: 'bg-destructive-soft text-destructive-ink',
        muted: 'bg-[#EEF5FB] text-[#3F5F7E]',
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
