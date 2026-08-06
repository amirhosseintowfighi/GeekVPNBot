'use client'

import * as React from 'react'

import { cn } from '@/lib/utils'

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  /**
   * Forces left-to-right for Latin identifiers: panel hostnames, coupon
   * codes, crypto addresses, transaction ids. Typing one of these into an RTL
   * field scrambles the character order on screen while the value is correct,
   * which is worse than being simply wrong - the operator cannot see the bug.
   */
  ltr?: boolean
  invalid?: boolean
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, ltr = false, invalid = false, ...props }, ref) => (
    <input
      ref={ref}
      dir={ltr ? 'ltr' : undefined}
      aria-invalid={invalid || undefined}
      className={cn(
        'flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm transition-colors',
        'placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        'disabled:cursor-not-allowed disabled:opacity-50',
        ltr && 'text-start font-mono',
        invalid && 'border-destructive focus-visible:ring-destructive',
        className,
      )}
      {...props}
    />
  ),
)
Input.displayName = 'Input'

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean
}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, invalid = false, ...props }, ref) => (
    <textarea
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(
        'flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm leading-loose',
        'placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        'disabled:cursor-not-allowed disabled:opacity-50',
        invalid && 'border-destructive focus-visible:ring-destructive',
        className,
      )}
      {...props}
    />
  ),
)
Textarea.displayName = 'Textarea'

/**
 * A labelled field with optional hint and error.
 *
 * The error replaces the hint rather than stacking below it, so the field's
 * height does not jump when validation fails and push the submit button out
 * from under the operator's cursor.
 */
export function Field({
  label,
  hint,
  error,
  required = false,
  htmlFor,
  children,
  className,
}: {
  label: string
  hint?: string
  error?: string | null
  required?: boolean
  htmlFor?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('space-y-1.5', className)}>
      <label htmlFor={htmlFor} className="flex items-center gap-1 text-xs font-medium">
        {label}
        {required ? <span className="text-destructive">*</span> : null}
      </label>
      {children}
      {error ? (
        <p className="text-2xs text-destructive">{error}</p>
      ) : hint ? (
        <p className="text-2xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  )
}

export { Input, Textarea }
