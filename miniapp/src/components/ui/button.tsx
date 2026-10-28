'use client'

import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

/**
 * The base button.
 *
 * Two decisions worth stating:
 *
 * - The default height is 44px, not shadcn's 40px. This lives inside a phone
 *   webview where a button is hit with a thumb, and 44px is the smallest
 *   comfortable target on iOS.
 * - `gap` handles icon spacing rather than a directional margin, so the layout
 *   flips correctly in RTL without a mirrored stylesheet.
 */
/**
 * Sky Lens buttons.
 *
 * `default` is the navy action - one per screen, the thing the screen is for.
 * `accent` is the logo blue with navy text, for an action sitting on a navy
 * panel. `secondary` is context-aware through `.soft`: clear glass on the blue
 * page, pale blue inside a card. `destructive` is the design's soft red, which
 * asks before it alarms. Every size keeps a 44px minimum touch target.
 */
const buttonVariants = cva(
  cn(
    'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-2xl',
    'font-bold transition-[transform,filter,background-color] duration-150',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-transparent',
    'disabled:pointer-events-none disabled:opacity-50',
    'active:scale-[0.98]',
    '[&_svg]:size-[18px] [&_svg]:shrink-0',
  ),
  {
    variants: {
      variant: {
        default:
          'bg-navy text-white shadow-[0_10px_24px_rgba(2,24,56,0.35)] hover:brightness-125',
        accent: 'bg-sky text-[color:var(--on-sky)] hover:brightness-105',
        secondary: 'soft hover:brightness-105',
        outline:
          'border border-[color:var(--line)] bg-transparent text-foreground hover:bg-[color:var(--soft-bg)]',
        ghost: 'text-foreground hover:bg-[color:var(--soft-bg)]',
        destructive:
          'border border-[color:var(--danger-line)] bg-destructive-soft text-destructive-ink hover:brightness-[0.98]',
        success: 'bg-success-ink text-white hover:brightness-110',
        link: 'h-auto px-1 text-link underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-[52px] px-5 text-[15px]',
        sm: 'h-11 rounded-xl px-4 text-[13px]',
        lg: 'h-[58px] rounded-[18px] px-6 text-[15px]',
        icon: 'size-11 rounded-[15px]',
      },
      full: {
        true: 'w-full',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
  loading?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant, size, full, asChild = false, loading, children, disabled, ...props },
    ref,
  ) => {
    const Comp = asChild ? Slot : 'button'

    return (
      <Comp
        className={cn(buttonVariants({ variant, size, full, className }))}
        ref={ref}
        // A loading button that stays clickable is how a customer ends up
        // paying twice.
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {/* With `asChild` the wrapper is Radix's Slot, and Slot runs
            React.Children.only. A spinner slot plus the child is two children
            even when the spinner is null, so every `<Button asChild>` threw
            "React.Children.only expected to receive a single React element
            child" - which is the client-side exception that took down the whole
            Mini App on first paint. A spinner has nothing to add to a link
            anyway. */}
        {asChild ? (
          children
        ) : (
          <>
            {loading ? <Spinner /> : null}
            {children}
          </>
        )}
      </Comp>
    )
  },
)
Button.displayName = 'Button'

function Spinner() {
  return (
    <span
      className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent"
      aria-hidden
    />
  )
}

export { Button, buttonVariants }
