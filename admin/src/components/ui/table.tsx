'use client'

import * as React from 'react'
import { ChevronsUpDown, ChevronUp, ChevronDown } from 'lucide-react'

import { cn } from '@/lib/utils'
import { faNumber } from '@/lib/fa'
import { Button } from './button'

/**
 * The table is the admin panel's primary object. Eleven of the fifteen
 * screens are a filtered list of something, so the decisions here are made
 * once and inherited everywhere.
 *
 * - Horizontal scroll lives on a wrapper, never on the page. A table that
 *   widens the document breaks the sidebar layout on every other screen.
 * - The header is sticky. An operator scrolling row 200 still needs to know
 *   which column holds the amount.
 * - Rows are 40px. Dense enough to see a working set, tall enough to click.
 */

const Table = React.forwardRef<HTMLTableElement, React.HTMLAttributes<HTMLTableElement>>(
  ({ className, ...props }, ref) => (
    <div className="relative w-full overflow-x-auto">
      <table
        ref={ref}
        className={cn('w-full caption-bottom border-collapse text-sm', className)}
        {...props}
      />
    </div>
  ),
)
Table.displayName = 'Table'

const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead
    ref={ref}
    className={cn('sticky top-0 z-20 bg-card [&_tr]:border-b [&_tr]:border-border', className)}
    {...props}
  />
))
TableHeader.displayName = 'TableHeader'

const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody ref={ref} className={cn('[&_tr:last-child]:border-0', className)} {...props} />
))
TableBody.displayName = 'TableBody'

const TableRow = React.forwardRef<
  HTMLTableRowElement,
  React.HTMLAttributes<HTMLTableRowElement> & { selected?: boolean }
>(({ className, selected = false, ...props }, ref) => (
  <tr
    ref={ref}
    data-selected={selected || undefined}
    className={cn(
      'border-b border-border transition-colors hover:bg-accent/40 data-[selected]:bg-primary/10',
      className,
    )}
    {...props}
  />
))
TableRow.displayName = 'TableRow'

const TableHead = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }
>(({ className, numeric = false, ...props }, ref) => (
  <th
    ref={ref}
    scope="col"
    className={cn(
      'h-9 px-3 text-start align-middle text-2xs font-medium text-muted-foreground whitespace-nowrap',
      // Numeric columns are end-aligned so digits line up under each other.
      numeric && 'text-end',
      className,
    )}
    {...props}
  />
))
TableHead.displayName = 'TableHead'

const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }
>(({ className, numeric = false, ...props }, ref) => (
  <td
    ref={ref}
    className={cn(
      'h-10 px-3 align-middle',
      numeric && 'nums text-end',
      className,
    )}
    {...props}
  />
))
TableCell.displayName = 'TableCell'

/** A sortable column header. Sorting is server-side; this only emits intent. */
export function SortableHead({
  label,
  columnKey,
  active,
  direction,
  onSort,
  numeric = false,
}: {
  label: string
  columnKey: string
  active: string | null
  direction: 'asc' | 'desc'
  onSort: (key: string) => void
  numeric?: boolean
}) {
  const isActive = active === columnKey
  const Icon = !isActive ? ChevronsUpDown : direction === 'asc' ? ChevronUp : ChevronDown

  return (
    <TableHead numeric={numeric} className="p-0">
      <button
        type="button"
        onClick={() => onSort(columnKey)}
        aria-sort={isActive ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'}
        className={cn(
          'flex h-9 w-full items-center gap-1 px-3 transition-colors hover:text-foreground',
          numeric ? 'justify-end' : 'justify-start',
          isActive && 'text-foreground',
        )}
      >
        {label}
        <Icon className="size-3" aria-hidden />
      </button>
    </TableHead>
  )
}

/**
 * Pagination.
 *
 * Deliberately shows the total row count. "Page 3 of 12" tells an operator
 * whether a filter actually narrowed anything, which a bare next/previous
 * pair cannot.
 */
export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  busy = false,
}: {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  busy?: boolean
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, total)

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-xs text-muted-foreground">
      <span className="nums">
        {'\u0646\u0645\u0627\u06cc\u0634 ' +
          faNumber(first) +
          '\u2013' +
          faNumber(last) +
          ' \u0627\u0632 ' +
          faNumber(total)}
      </span>

      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={page <= 1 || busy}
          onClick={() => onPageChange(page - 1)}
        >
          {'\u0642\u0628\u0644\u06cc'}
        </Button>
        <span className="nums px-1">
          {faNumber(page) + ' / ' + faNumber(pageCount)}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={page >= pageCount || busy}
          onClick={() => onPageChange(page + 1)}
        >
          {'\u0628\u0639\u062f\u06cc'}
        </Button>
      </div>
    </div>
  )
}

export { Table, TableHeader, TableBody, TableRow, TableHead, TableCell }
