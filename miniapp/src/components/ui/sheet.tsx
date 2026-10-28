'use client'

import * as React from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'

import { cn } from '@/lib/utils'

/**
 * Bottom sheet.
 *
 * Every modal surface in this app slides up from the bottom rather than
 * centering, because the whole product is used one-handed inside Telegram and
 * a centered dialog puts its actions out of thumb reach. The grab handle is
 * decorative but it is the affordance people look for before they try to
 * swipe a sheet away.
 */
const Sheet = DialogPrimitive.Root
const SheetTrigger = DialogPrimitive.Trigger
const SheetClose = DialogPrimitive.Close
const SheetPortal = DialogPrimitive.Portal

const SheetOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      'fixed inset-0 z-50 bg-[rgba(3,24,56,0.5)] backdrop-blur-[2px]',
      'data-[state=open]:animate-in data-[state=closed]:animate-out',
      'data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0',
      className,
    )}
    {...props}
  />
))
SheetOverlay.displayName = 'SheetOverlay'

const SheetContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    hideClose?: boolean
  }
>(({ className, children, hideClose, ...props }, ref) => (
  <SheetPortal>
    <SheetOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        'fixed inset-x-0 bottom-0 z-50 mx-auto w-full max-w-2xl',
        // Opaque white rather than glass: a sheet holds a form or a payment
        // choice, and the blurred page behind it only competes with that.
        'milk max-h-[92dvh] overflow-y-auto rounded-t-[30px] bg-white',
        'px-5 pb-[calc(1.5rem+var(--tg-safe-bottom))] pt-3 shadow-[0_-20px_50px_rgba(2,24,56,0.35)]',
        'data-[state=open]:animate-in data-[state=closed]:animate-out',
        'data-[state=open]:slide-in-from-bottom data-[state=closed]:slide-out-to-bottom',
        'duration-300',
        className,
      )}
      {...props}
    >
      <div
        aria-hidden
        className="mx-auto mb-4 h-[5px] w-11 rounded-full bg-[#C9D9E7]"
      />
      {children}
      {hideClose ? null : (
        <DialogPrimitive.Close
          className={cn(
            'absolute left-4 top-4 flex size-9 items-center justify-center rounded-xl',
            'bg-[#EEF5FB] text-[#3F5F7E] transition-colors hover:text-[#062845]',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          )}
        >
          <X className="size-4" aria-hidden />
          <span className="sr-only">{'\u0628\u0633\u062a\u0646'}</span>
        </DialogPrimitive.Close>
      )}
    </DialogPrimitive.Content>
  </SheetPortal>
))
SheetContent.displayName = 'SheetContent'

function SheetHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('mb-4 space-y-1.5 pe-8', className)} {...props} />
}

const SheetTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn('text-lg font-extrabold', className)}
    {...props}
  />
))
SheetTitle.displayName = 'SheetTitle'

const SheetDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn('text-sm leading-relaxed text-muted-foreground', className)}
    {...props}
  />
))
SheetDescription.displayName = 'SheetDescription'

export {
  Sheet,
  SheetTrigger,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
}
