'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import { ChevronRight } from 'lucide-react'

import { cn } from '@/lib/utils'
import { haptic, useTelegramBackButton } from '@/lib/telegram'

/**
 * Header for every screen below the tab bar.
 *
 * Two things are deliberate here.
 *
 * First, the native Telegram BackButton is wired to the same handler as the
 * on-screen chevron. Telegram clients render their own back control and users
 * reach for it first; if it is left unbound it either does nothing or closes
 * the whole Mini App, which reads as a crash. `useTelegramBackButton` is a
 * no-op in a plain browser, so the visible chevron is the fallback.
 *
 * Second, the chevron points right. In an RTL layout "back" is toward the
 * start of the line, which is the right edge.
 */
export function PageHeader({
  title,
  subtitle,
  action,
  back = true,
  onBack,
  className,
}: {
  title: string
  subtitle?: string
  action?: React.ReactNode
  back?: boolean
  onBack?: () => void
  className?: string
}) {
  const router = useRouter()

  const handleBack = React.useCallback(() => {
    haptic.impact('light')
    if (onBack) {
      onBack()
      return
    }
    router.back()
  }, [onBack, router])

  // null, not undefined: the hook spells "no handler, hide the button" as null.
  useTelegramBackButton(back ? handleBack : null)

  return (
    <header
      className={cn(
        'safe-top sticky top-0 z-30 -mx-4 mb-4 px-4 pb-3 pt-3',
        'border-b border-border/60 bg-background/85 backdrop-blur-xl',
        className,
      )}
    >
      <div className="flex items-center gap-2">
        {back ? (
          <button
            type="button"
            onClick={handleBack}
            aria-label="\u0628\u0627\u0632\u06af\u0634\u062a"
            className={cn(
              '-me-1 shrink-0 rounded-full p-2 text-muted-foreground',
              'transition-colors hover:bg-secondary hover:text-foreground',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            )}
          >
            <ChevronRight className="size-5" aria-hidden />
          </button>
        ) : null}

        <div className="min-w-0 flex-1">
          <h1 className="truncate text-base font-semibold leading-tight">
            {title}
          </h1>
          {subtitle ? (
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {subtitle}
            </p>
          ) : null}
        </div>

        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
    </header>
  )
}
