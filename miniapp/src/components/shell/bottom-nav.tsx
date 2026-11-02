'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { motion } from 'framer-motion'
import {
  Home,
  Layers,
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
 * `Layers` is "my services", the equivalent of /services in the bot.
 */
const TABS = [
  { href: '/', label: 'خانه', icon: Home },
  { href: '/shop', label: 'فروشگاه', icon: ShoppingBag },
  {
    href: '/services',
    label: 'سرویس‌ها',
    icon: Layers,
  },
  { href: '/wallet', label: 'کیف پول', icon: Wallet },
  { href: '/profile', label: 'حساب', icon: User },
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
      <div aria-hidden className="h-[104px] shrink-0" />
      <nav
        className="safe-bottom fixed inset-x-0 bottom-0 z-40 mx-auto w-full max-w-2xl px-[18px] pb-4"
        aria-label="نوار پیمایش اصلی"
      >
        {/* One floating slab of glass, square-shouldered with softened corners.
            Only the current tab carries its name, on solid white; the others
            are icons, so five fit a narrow phone. */}
        <ul className="glass-clear flex h-16 items-center justify-between rounded-[18px] px-1.5">
          {TABS.map((tab) => {
            // Every route except home matches by prefix, so a nested page such
            // as /shop/<plan> keeps its parent tab lit.
            const active =
              tab.href === '/'
                ? pathname === '/'
                : pathname.startsWith(tab.href)
            const Icon = tab.icon

            return (
              <li key={tab.href} className="relative">
                <Link
                  href={tab.href}
                  onClick={haptic.select}
                  aria-current={active ? 'page' : undefined}
                  aria-label={tab.label}
                  className={cn(
                    'relative flex h-[52px] items-center gap-[7px] rounded-[12px]',
                    active ? 'px-4 text-on-action' : 'px-3 text-white/75',
                    'transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white',
                  )}
                >
                  {/* The white tile slides between tabs instead of fading in
                      and out on each; layoutId is what makes it one movement. */}
                  {active ? (
                    <motion.span
                      layoutId="tab-indicator"
                      className="absolute inset-0 rounded-[12px] bg-action"
                      transition={{ type: 'spring', stiffness: 420, damping: 34 }}
                    />
                  ) : null}
                  <Icon className="relative size-5" strokeWidth={2} aria-hidden />
                  {active ? (
                    <span className="relative whitespace-nowrap text-[14px] font-extrabold">
                      {tab.label}
                    </span>
                  ) : null}
                </Link>
              </li>
            )
          })}
        </ul>
      </nav>
    </>
  )
}
