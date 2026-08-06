'use client'

import * as React from 'react'

import { cn } from '@/lib/utils'

export function Separator({
  className,
  orientation = 'horizontal',
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  orientation?: 'horizontal' | 'vertical'
}) {
  return (
    <div
      role="separator"
      aria-orientation={orientation}
      className={cn(
        'shrink-0 bg-border',
        orientation === 'horizontal' ? 'h-px w-full' : 'h-full w-px',
        className,
      )}
      {...props}
    />
  )
}

/**
 * A labelled rule, used to break long forms into sections without spending a
 * heading level on them.
 */
export function SeparatorLabel({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex items-center gap-3', className)}>
      <Separator className="flex-1" />
      <span className="text-xs text-muted-foreground">{children}</span>
      <Separator className="flex-1" />
    </div>
  )
}
