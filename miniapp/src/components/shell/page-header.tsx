'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import { ChevronRight } from 'lucide-react'

import { cn } from '@/lib/utils'
import { haptic, useTelegramBackButton } from '@/lib/telegram'
import useSWR from 'swr'

import { GlassesMark } from '@/components/brand/glasses-mark'
import { fetcher } from '@/lib/api'
import { shopId } from '@/lib/shop'
import type { ShopInfo } from '@/lib/types'

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
 *
 * Not sticky, as the design draws it: the title is part of the page, and
 * Telegram's own back control stays on screen while the content scrolls.
 */
export function PageHeader({
  title,
  subtitle,
  eyebrow,
  action,
  back = true,
  onBack,
  className,
}: {
  title: string
  subtitle?: string
  /** The small Latin caption over the title, the design's "Shop", "Wallet". */
  eyebrow?: string
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
    // Opened straight from a bot button, the screen is the first entry in
    // the webview's history, and back() there does nothing at all.
    if (window.history.length > 1) router.back()
    else router.replace('/')
  }, [onBack, router])

  // null, not undefined: the hook spells "no handler, hide the button" as null.
  useTelegramBackButton(back ? handleBack : null)

  return (
    <header className={cn('safe-top mb-5 flex flex-col gap-4 pt-2', className)}>
      {/* The top row: the brand on a tab root, the way back below one. */}
      <div className="flex min-h-10 items-center justify-between gap-3">
        {back ? (
          <button
            type="button"
            onClick={handleBack}
            aria-label="بازگشت"
            className={cn(
              'glass-clear flex size-10 shrink-0 items-center justify-center rounded-full',
              'transition-transform active:scale-95',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white',
            )}
          >
            <ChevronRight className="size-[18px]" strokeWidth={2.2} aria-hidden />
          </button>
        ) : (
          <BrandRow />
        )}
        {action ? <div className="shrink-0">{action}</div> : eyebrow && back ? (
          <span className="eyebrow">{eyebrow}</span>
        ) : null}
      </div>

      {back ? null : <div className="hairline" />}

      <div className="flex min-w-0 flex-col gap-1">
        {eyebrow && (!back || action) ? <span className="eyebrow">{eyebrow}</span> : null}
        <h1 className="text-[32px] font-extrabold leading-tight">{title}</h1>
        {subtitle ? (
          <p className="text-[14px] font-medium leading-relaxed text-muted-foreground">
            {subtitle}
          </p>
        ) : null}
      </div>
    </header>
  )
}

/**
 * The glasses and the name, as the design opens every tab root.
 *
 * A reseller's shop shows their name and no mark: our brand is not theirs to
 * wear. Which one is decided from the URL, not the API, so neither flashes by
 * while the shop's name loads.
 */
export function BrandRow() {
  const [inShop, setInShop] = React.useState(false)
  React.useEffect(() => setInShop(shopId() !== null), [])
  const shop = useSWR<ShopInfo>(inShop ? '/api/miniapp/shop' : null, fetcher)

  if (inShop) {
    return (
      <p className="min-w-0 flex-1 truncate text-xl font-extrabold leading-none">
        {shop.data?.brandFa ?? ''}
      </p>
    )
  }
  return (
    <div className="flex shrink-0 items-center gap-2">
      <GlassesMark className="h-[19px] w-[39px] text-white" />
      <span dir="ltr" className="font-display text-[18px] font-bold tracking-[-0.5px] text-white">
        GeekVPN
      </span>
    </div>
  )
}
