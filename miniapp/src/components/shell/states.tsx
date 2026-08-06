'use client'

import * as React from 'react'
import { motion } from 'framer-motion'
import { AlertTriangle, Inbox, RefreshCw, WifiOff } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { itemVariants, listVariants } from '@/lib/motion'
import { cn } from '@/lib/utils'

/**
 * Empty, error and loading placeholders.
 *
 * These live in one file because they are the three branches of the same
 * decision and keeping them together makes it obvious when one of them is
 * missing from a screen.
 */

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ComponentType<{ className?: string }>
  title: string
  description?: string
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 px-6 py-14 text-center',
        className,
      )}
    >
      <div className="rounded-2xl border border-border/70 bg-secondary/40 p-4">
        <Icon className="size-7 text-muted-foreground" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium">{title}</p>
        {description ? (
          <p className="mx-auto max-w-xs text-xs leading-loose text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {action ? <div className="pt-1">{action}</div> : null}
    </div>
  )
}

/**
 * Error placeholder.
 *
 * `messageFa` comes from ApiError, which always carries a Persian sentence -
 * the raw English fetch failure is never shown. Offline is separated out
 * because the remedy is different and users act on it themselves.
 */
export function ErrorState({
  messageFa,
  offline,
  onRetry,
  className,
}: {
  messageFa?: string
  offline?: boolean
  onRetry?: () => void
  className?: string
}) {
  const Icon = offline ? WifiOff : AlertTriangle
  const fallback = offline
    ? '\u0627\u062a\u0635\u0627\u0644 \u0627\u06cc\u0646\u062a\u0631\u0646\u062a \u0628\u0631\u0642\u0631\u0627\u0631 \u0646\u06cc\u0633\u062a.'
    : '\u0645\u0634\u06a9\u0644\u06cc \u067e\u06cc\u0634 \u0622\u0645\u062f. \u0644\u0637\u0641\u0627\u064b \u062f\u0648\u0628\u0627\u0631\u0647 \u062a\u0644\u0627\u0634 \u06a9\u0646\u06cc\u062f.'

  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col items-center justify-center gap-3 px-6 py-12 text-center',
        className,
      )}
    >
      <div className="rounded-2xl border border-destructive/30 bg-destructive/10 p-4">
        <Icon className="size-7 text-destructive" />
      </div>
      <p className="max-w-xs text-sm leading-loose text-muted-foreground">
        {messageFa || fallback}
      </p>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="size-4" aria-hidden />
          \u062a\u0644\u0627\u0634 \u062f\u0648\u0628\u0627\u0631\u0647
        </Button>
      ) : null}
    </div>
  )
}

/**
 * Wraps a list so children stagger in. Kept tiny on purpose: the stagger is
 * 40ms per item, which reads as one movement rather than a queue.
 */
export function StaggerList({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <motion.div
      variants={listVariants}
      initial="hidden"
      animate="show"
      className={className}
    >
      {children}
    </motion.div>
  )
}

export function StaggerItem({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <motion.div variants={itemVariants} className={className}>
      {children}
    </motion.div>
  )
}
