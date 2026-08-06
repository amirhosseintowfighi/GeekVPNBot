'use client'

import * as React from 'react'

import { cn } from '@/lib/utils'

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  /**
   * Render the value left-to-right while keeping the field in an RTL page.
   * Use for coupon codes, crypto addresses, transaction hashes, phone
   * numbers - anything Latin whose characters would otherwise be reordered.
   */
  ltr?: boolean
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ltr, ...props }, ref) => {
    return (
      <input
        type={type}
        ref={ref}
        dir={ltr ? 'ltr' : undefined}
        className={cn(
          'flex h-11 w-full rounded-md border border-input bg-secondary/40 px-3 py-2',
          // 16px is the threshold below which iOS Safari zooms the viewport on
          // focus. In a Telegram webview that zoom cannot be undone by the
          // user, so the base size is locked at text-base on small screens.
          'text-base sm:text-sm',
          'placeholder:text-muted-foreground',
          'transition-colors focus-visible:border-primary/60 focus-visible:outline-none',
          'focus-visible:ring-2 focus-visible:ring-ring/40',
          'disabled:cursor-not-allowed disabled:opacity-50',
          ltr && 'text-left font-mono tracking-wide',
          className,
        )}
        {...props}
      />
    )
  },
)
Input.displayName = 'Input'

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        'flex min-h-24 w-full rounded-md border border-input bg-secondary/40 px-3 py-2',
        'text-base leading-relaxed sm:text-sm',
        'placeholder:text-muted-foreground',
        'transition-colors focus-visible:border-primary/60 focus-visible:outline-none',
        'focus-visible:ring-2 focus-visible:ring-ring/40',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  ),
)
Textarea.displayName = 'Textarea'

export { Input, Textarea }
