'use client'

import { AlertTriangle, Inbox, Lock, WifiOff } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/**
 * The four things a screen can show instead of data. Centralised so that an
 * empty orders table and an empty logs table look and behave identically.
 */

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon
  title: string
  description?: string
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-2 px-6 py-14 text-center', className)}>
      <Icon className="size-8 text-muted-foreground/60" aria-hidden />
      <p className="text-sm font-medium">{title}</p>
      {description ? (
        <p className="max-w-sm text-xs text-muted-foreground">{description}</p>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  )
}

/**
 * An error, split by cause.
 *
 * Offline and server-side failures get different icons and different copy,
 * because they send the operator to two different places: their own network,
 * or the on-call engineer. Collapsing them into one "something went wrong"
 * wastes the first five minutes of an incident.
 */
export function ErrorState({
  messageFa,
  offline = false,
  onRetry,
  className,
}: {
  messageFa: string
  offline?: boolean
  onRetry?: () => void
  className?: string
}) {
  const Icon = offline ? WifiOff : AlertTriangle

  return (
    <div className={cn('flex flex-col items-center justify-center gap-3 px-6 py-14 text-center', className)}>
      <Icon className={cn('size-8', offline ? 'text-muted-foreground' : 'text-destructive')} aria-hidden />
      <p className="max-w-sm text-sm">{messageFa}</p>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          {'\u062a\u0644\u0627\u0634 \u062f\u0648\u0628\u0627\u0631\u0647'}
        </Button>
      ) : null}
    </div>
  )
}

/**
 * Shown when the operator's role does not carry the permission a screen
 * requires.
 *
 * It names the missing permission rather than pretending the page does not
 * exist. An operator who knows what to ask for gets unblocked in one message;
 * a mysterious blank page turns into a support thread.
 */
export function ForbiddenState({ permission }: { permission?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-20 text-center">
      <Lock className="size-8 text-muted-foreground/60" aria-hidden />
      <p className="text-sm font-medium">
        {'\u062f\u0633\u062a\u0631\u0633\u06cc \u0646\u062f\u0627\u0631\u06cc\u062f'}
      </p>
      <p className="max-w-sm text-xs text-muted-foreground">
        {'\u0627\u06cc\u0646 \u0628\u062e\u0634 \u0628\u0631\u0627\u06cc \u0646\u0642\u0634 \u0634\u0645\u0627 \u0641\u0639\u0627\u0644 \u0646\u06cc\u0633\u062a. \u0627\u0632 \u0645\u0627\u0644\u06a9 \u0628\u062e\u0648\u0627\u0647\u06cc\u062f \u062f\u0633\u062a\u0631\u0633\u06cc \u0632\u06cc\u0631 \u0631\u0627 \u0628\u0647 \u0634\u0645\u0627 \u0628\u062f\u0647\u062f:'}
      </p>
      {permission ? (
        <code dir="ltr" className="rounded bg-muted px-2 py-1 font-mono text-2xs">
          {permission}
        </code>
      ) : null}
    </div>
  )
}
