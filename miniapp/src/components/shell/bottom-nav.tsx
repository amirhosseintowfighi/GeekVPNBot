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

  // Shown on the five tab roots only. A screen below them - checkout, a
  // payment, a ticket - has a back button and usually its own sticky action,
  // and a tab bar there both crowds that action and invites leaving a payment
  // half-done, which is what the Android and desktop clients avoid too.
  if (!TABS.some((tab) => tab.href === pathname)) return null

  return (
    <>
    {/* Holds the bottom of the page clear of the floating bar. */}
    <div aria-hidden className="h-[124px] shrink-0" />
    <nav
      className={cn(
        'safe-bottom fixed inset-x-0 bottom-0 z-40 mx-auto w-full max-w-2xl',
        // Floating tiles rather than a bar. The fade underneath is what keeps
        // the labels legible when a white card scrolls behind them - they are
        // white text, and white on milky glass would vanish.
        'bg-gradient-to-t from-background from-55% via-background/90 to-transparent pt-6',
      )}
      aria-label="\u0646\u0648\u0627\u0631 \u067e\u06cc\u0645\u0627\u06cc\u0634 \u0627\u0635\u0644\u06cc"
    >
      <ul className="flex items-end justify-between gap-1.5 px-3 pb-1">
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
                  'group flex flex-col items-center gap-1 rounded-2xl pb-1 text-white',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white',
                )}
              >
                <span className="relative flex h-[52px] w-full max-w-[60px] items-center justify-center">
                  {/*
                    The milky tile slides between tabs instead of fading in
                    and out on each; layoutId is what makes it one movement.
                  */}
                  {active ? (
                    <motion.span
                      layoutId="tab-indicator"
                      className="glass absolute inset-0 rounded-[18px]"
                      transition={{ type: 'spring', stiffness: 420, damping: 34 }}
                    />
                  ) : (
                    <span className="glass-clear absolute inset-1 rounded-2xl transition-transform group-active:scale-95" />
                  )}
                  <Icon
                    className={cn(
                      'relative size-[22px]',
                      active ? 'text-navy' : 'text-white',
                    )}
                    strokeWidth={active ? 2.3 : 2}
                    aria-hidden
                  />
                </span>
                <span
                  className={cn(
                    'max-w-full truncate text-[11px] leading-4',
                    active ? 'font-extrabold' : 'font-medium',
                  )}
                >
                  {tab.label}
                </span>
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
    </>
  )
}
