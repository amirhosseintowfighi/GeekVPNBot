'use client'

import * as React from 'react'
import Link from 'next/link'
import { ChevronLeft } from 'lucide-react'

import { cn } from '@/lib/utils'

/**
 * The heading block every screen starts with.
 *
 * `actions` sits at the end of the line (the left in this RTL panel) so the
 * primary action lands in the same place on all fifteen screens. On narrow
 * widths the row wraps instead of shrinking the title, because a truncated
 * page title is more disorienting than a two-line header.
 */
export function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
  className,
}: {
  title: string
  description?: string
  actions?: React.ReactNode
  breadcrumb?: { href: string; labelFa: string }
  className?: string
}) {
  return (
    <div className={cn('mb-4 flex flex-wrap items-start justify-between gap-3', className)}>
      <div className="min-w-0 space-y-1">
        {breadcrumb ? (
          <Link
            href={breadcrumb.href}
            className="inline-flex items-center gap-1 text-2xs text-muted-foreground transition-colors hover:text-foreground"
          >
            {/*
              Chevron points LEFT here. "Back" in an RTL layout is toward the
              start of the line, which is the right - but this is a
              breadcrumb, read as a step outward in the hierarchy, so it
              follows the forward reading direction like the menu rows do.
            */}
            <ChevronLeft className="size-3" aria-hidden />
            {breadcrumb.labelFa}
          </Link>
        ) : null}

        <h1 className="truncate text-base font-semibold">{title}</h1>

        {description ? (
          <p className="max-w-2xl text-xs text-muted-foreground">{description}</p>
        ) : null}
      </div>

      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}

/**
 * The filter bar above a table.
 *
 * Always full width and always wrapping, so adding a fourth filter to a
 * screen never pushes the search box off the edge on a laptop.
 */
export function Toolbar({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-2 border-b border-border px-3 py-2.5',
        className,
      )}
    >
      {children}
    </div>
  )
}
