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
          // A filled field, not an outlined one: the design's inputs are pale
          // wells inside a card, and an outline on milky glass reads as noise.
          'flex h-[52px] w-full rounded-[14px] border border-transparent bg-input px-4 py-2 text-[color:var(--field-ink)]',
          // 16px is the threshold below which iOS Safari zooms the viewport on
          // focus. In a Telegram webview that zoom cannot be undone by the
          // user, so the base size is locked at text-base on small screens.
          'text-base sm:text-sm',
          'placeholder:text-[color:var(--placeholder)]',
          'transition-colors focus-visible:border-[color:var(--tint)] focus-visible:bg-[color:var(--sheet)] focus-visible:outline-none',
          'focus-visible:ring-4 focus-visible:ring-[color:var(--tint-ring)]',
          'disabled:cursor-not-allowed disabled:opacity-50',
          ltr && 'font-display text-left tracking-wide',
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
        'flex min-h-28 w-full rounded-[14px] border border-transparent bg-input px-4 py-3 text-[color:var(--field-ink)]',
        'text-base leading-relaxed sm:text-sm',
        'placeholder:text-[color:var(--placeholder)]',
        'transition-colors focus-visible:border-[color:var(--tint)] focus-visible:bg-[color:var(--sheet)] focus-visible:outline-none',
        'focus-visible:ring-4 focus-visible:ring-[color:var(--tint-ring)]',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  ),
)
Textarea.displayName = 'Textarea'

export { Input, Textarea }
