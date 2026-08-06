'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { motion } from 'framer-motion'
import {
  Home,
  LayoutGrid,
  ShoppingBag,
  User,
  Wallet,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import { haptic } from '@/lib/telegram'

/**
 * The primary tab bar.
 *
 * Five tabs, deliberately. Telegram's own webview is narrow and a sixth item
 * pushes each target under the comfortable thumb size. The rest of the bot's
 * surface - support, FAQ, settings, server status, referral - lives one level
 * down under the profile tab, which mirrors how the bot's own menu is
 * organised rather than inventing a second information architecture.
 *
 * `LayoutGrid` is "my services", the equivalent of /services in the bot.
 */
const TABS = [
  { href: '/', label: '\u062e\u0627\u0646\u0647', icon: Home },
  { href: '/shop', label: '\u0641\u0631\u0648\u0634\u06af\u0627\u0647', icon: ShoppingBag },
  {
    href: '/services',
    label: '\u0633\u0631\u0648\u06cc\u0633\u200c\u0647\u0627\u06cc \u0645\u0646',
    icon: LayoutGrid,
  },
  { href: '/wallet', label: '\u06a9\u06cc\u0641 \u067e\u0648\u0644', icon: Wallet },
  { href: '/profile', label: '\u067e\u0631\u0648\u0641\u0627\u06cc\u0644', icon: User },
] as const

export function BottomNav() {
  const pathname = usePathname()

  return (
    <nav
      className={cn(
        'safe-bottom fixed inset-x-0 bottom-0 z-40 mx-auto w-full max-w-2xl',
        // The blur keeps the bar legible over whatever scrolls beneath it
        // without needing an opaque slab that would eat vertical space.
        'border-t border-border/70 bg-background/85 backdrop-blur-xl',
      )}
      aria-label="\u0646\u0648\u0627\u0631 \u067e\u06cc\u0645\u0627\u06cc\u0634 \u0627\u0635\u0644\u06cc"
    >
      <ul className="flex items-stretch justify-around px-1 pt-1">
        {TABS.map((tab) => {
          // Every route except home matches by prefix, so a nested page such
          // as /shop/<plan> keeps its parent tab lit.
          const active =
            tab.href === '/'
              ? pathname === '/'
              : pathname.startsWith(tab.href)
          const Icon = tab.icon

          return (
            <li key={tab.href} className="relative flex-1">
              <Link
                href={tab.href}
                onClick={haptic.select}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'flex h-14 flex-col items-center justify-center gap-1 rounded-md',
                  'text-[11px] font-medium transition-colors',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  active ? 'text-foreground' : 'text-muted-foreground',
                )}
              >
                <Icon
                  className={cn('size-5 transition-transform', active && 'scale-110')}
                  aria-hidden
                />
                <span>{tab.label}</span>
              </Link>

              {/*
                A single shared indicator that slides between tabs, rather than
                one that fades in and out per tab. layoutId is what makes the
                movement continuous.
              */}
              {active ? (
                <motion.span
                  layoutId="tab-indicator"
                  className="absolute inset-x-4 top-0 h-0.5 rounded-full bg-brand-gradient"
                  transition={{ type: 'spring', stiffness: 400, damping: 34 }}
                />
              ) : null}
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
