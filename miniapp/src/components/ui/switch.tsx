'use client'

import * as React from 'react'
import * as SwitchPrimitives from '@radix-ui/react-switch'

import { cn } from '@/lib/utils'

/**
 * Toggle, used throughout the settings screen.
 *
 * The thumb translation is negated relative to the shadcn default: in an RTL
 * layout the track's "on" end is the left one, so an unmodified LTR switch
 * animates the thumb the wrong way and reads as broken.
 */
const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitives.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitives.Root
    ref={ref}
    className={cn(
      // The design's pill: 44x26, solid white when on, dim glass when off.
      'peer inline-flex h-[26px] w-[44px] shrink-0 cursor-pointer items-center rounded-full border border-transparent p-[2px]',
      'transition-colors',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
      'disabled:cursor-not-allowed disabled:opacity-50',
      'data-[state=checked]:bg-action data-[state=unchecked]:border-white/30 data-[state=unchecked]:bg-[color:var(--switch-off)]',
      className,
    )}
    {...props}
  >
    <SwitchPrimitives.Thumb
      className={cn(
        'pointer-events-none block size-5 rounded-full shadow-md ring-0',
        'transition-[transform,background-color]',
        'data-[state=checked]:-translate-x-[18px] data-[state=checked]:bg-on-action',
        'data-[state=unchecked]:translate-x-0 data-[state=unchecked]:bg-white',
      )}
    />
  </SwitchPrimitives.Root>
))
Switch.displayName = SwitchPrimitives.Root.displayName

export { Switch }
