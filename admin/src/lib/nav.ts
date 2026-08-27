import {
  BadgePercent,
  Boxes,
  ChartNoAxesCombined,
  FileClock,
  Handshake,
  LayoutDashboard,
  LifeBuoy,
  Megaphone,
  Receipt,
  Server,
  ServerCog,
  Settings,
  ShieldCheck,
  Sparkles,
  Users,
  Wallet,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import type { Permission } from './rbac'

/**
 * The single source of truth for navigation.
 *
 * Every entry declares the permission that gates it, so the sidebar, the
 * command palette and the route guard all agree by construction. A screen
 * added here without a permission would be visible to everyone, which is why
 * the field is required rather than optional.
 *
 * Order is by how often an operator needs the screen during a shift, not
 * alphabetically and not by how interesting the feature is. Orders and
 * tickets sit near the top because those are the two queues with a customer
 * waiting at the other end.
 */
export interface NavItem {
  href: string
  labelFa: string
  icon: LucideIcon
  permission: Permission
  /** Key into the dashboard ActionQueue, rendered as a count badge. */
  /** Matches ActionItem.key from GET /api/v1/admin/analytics/dashboard. */
  queueKey?: 'pending_payments' | 'open_tickets' | 'offline_nodes'
  /**
   * Reachable, but not a sidebar destination.
   *
   * The route guard denies any path this table does not cover - correctly, a
   * screen missing from it is a bug rather than a door to leave open. But
   * subscriptions are only ever reached from a customer, so listing them in
   * the sidebar would be a menu entry leading to a page that needs an id.
   * Without an entry of some kind, clicking a customer's subscription showed
   * "your role does not have access", to an owner who has every permission
   * there is.
   */
  hidden?: boolean
}

export interface NavSection {
  titleFa: string
  items: NavItem[]
}

export const NAV: NavSection[] = [
  {
    // A reseller's whole panel. They hold `reseller.portal` and nothing else,
    // so every other section resolves to a permission they do not have and
    // disappears - which is why this can sit at the top for them and be
    // invisible to staff, who deliberately do not hold it.
    titleFa: 'نمایندگی',
    items: [
      {
        href: '/portal',
        labelFa: 'پنل من',
        icon: Handshake,
        permission: 'reseller.portal',
      },
    ],
  },
  {
    titleFa: '\u0645\u0631\u0648\u0631',
    items: [
      {
        href: '/',
        labelFa: '\u062f\u0627\u0634\u0628\u0648\u0631\u062f',
        icon: LayoutDashboard,
        permission: 'analytics.view',
      },
      {
        href: '/analytics',
        labelFa: '\u062a\u062d\u0644\u06cc\u0644\u200c\u0647\u0627',
        icon: ChartNoAxesCombined,
        permission: 'analytics.view',
      },
    ],
  },
  {
    titleFa: '\u0639\u0645\u0644\u06cc\u0627\u062a',
    items: [
      {
        // Above orders on purpose: a payment in this queue is a customer who
        // has already sent money and is waiting. Nothing else on this list
        // outranks that.
        href: '/payments',
        labelFa: 'بررسی پرداخت‌ها',
        icon: Receipt,
        permission: 'payments.read',
        queueKey: 'pending_payments',
      },
      {
        // The badge belongs to the review queue above, not here: a pending
        // payment is acted on there, and two entries counting the same thing
        // makes neither of them mean anything.
        href: '/orders',
        labelFa: '\u0633\u0641\u0627\u0631\u0634\u200c\u0647\u0627',
        icon: Receipt,
        permission: 'orders.read',
      },
      {
        href: '/tickets',
        labelFa: '\u062a\u06cc\u06a9\u062a\u200c\u0647\u0627',
        icon: LifeBuoy,
        permission: 'tickets.read',
        queueKey: 'open_tickets',
      },
      {
        href: '/users',
        labelFa: '\u06a9\u0627\u0631\u0628\u0631\u0627\u0646',
        icon: Users,
        permission: 'users.read',
      },
      {
        href: '/wallet',
        labelFa: '\u06a9\u06cc\u0641 \u067e\u0648\u0644',
        icon: Wallet,
        permission: 'wallet.read',
      },
      {
        // Under operations rather than management: a reseller with no credit
        // is a queue with customers waiting behind it, the same shape as a
        // pending payment.
        href: '/resellers',
        labelFa: 'نمایندگان',
        icon: Handshake,
        permission: 'resellers.read',
      },
      {
        href: '/subscriptions',
        labelFa: '\u0627\u0634\u062a\u0631\u0627\u06a9\u200c\u0647\u0627',
        icon: Wallet,
        permission: 'subscriptions.read',
        hidden: true,
      },
    ],
  },
  {
    titleFa: '\u0645\u062d\u0635\u0648\u0644\u0627\u062a',
    items: [
      {
        href: '/products',
        labelFa: '\u0645\u062d\u0635\u0648\u0644\u0627\u062a \u0648 \u067e\u0644\u0646\u200c\u0647\u0627',
        icon: Boxes,
        permission: 'packages.read',
      },
      {
        href: '/coupons',
        labelFa: '\u06a9\u062f\u0647\u0627\u06cc \u062a\u062e\u0641\u06cc\u0641',
        icon: BadgePercent,
        permission: 'packages.read',
      },
      {
        href: '/campaigns',
        labelFa: '\u06a9\u0645\u067e\u06cc\u0646\u200c\u0647\u0627',
        icon: Sparkles,
        permission: 'packages.read',
      },
      {
        href: '/broadcast',
        labelFa: '\u067e\u06cc\u0627\u0645 \u0647\u0645\u06af\u0627\u0646\u06cc',
        icon: Megaphone,
        permission: 'broadcast.read',
      },
    ],
  },
  {
    titleFa: '\u0632\u06cc\u0631\u0633\u0627\u062e\u062a',
    items: [
      {
        href: '/panels',
        labelFa: '\u067e\u0646\u0644\u200c\u0647\u0627',
        icon: ServerCog,
        permission: 'panels.read',
        queueKey: 'offline_nodes',
      },
      {
        href: '/servers',
        labelFa: '\u0633\u0631\u0648\u0631\u0647\u0627',
        icon: Server,
        permission: 'panels.read',
      },
      {
        href: '/logs',
        labelFa: '\u0644\u0627\u06af\u200c\u0647\u0627',
        icon: FileClock,
        permission: 'audit.read',
      },
    ],
  },
  {
    titleFa: '\u0645\u062f\u06cc\u0631\u06cc\u062a',
    items: [
      {
        href: '/settings',
        labelFa: '\u062a\u0646\u0638\u06cc\u0645\u0627\u062a',
        icon: Settings,
        permission: 'settings.read',
      },
      {
        href: '/permissions',
        labelFa: '\u062f\u0633\u062a\u0631\u0633\u06cc\u200c\u0647\u0627',
        icon: ShieldCheck,
        permission: 'admins.read',
      },
    ],
  },
]

/** Flat lookup used by the route guard and the page title resolver. */
export const NAV_ITEMS: NavItem[] = NAV.flatMap((section) => section.items)

/**
 * Resolves the permission protecting a pathname.
 *
 * Matching is longest-prefix so that a detail route like `/orders/abc`
 * inherits the guard on `/orders`. The root entry is compared exactly,
 * otherwise it would match every path in the app and grant the whole panel
 * to anyone holding `dashboard.view`.
 */
export function permissionForPath(pathname: string): Permission | null {
  if (pathname === '/') return 'analytics.view'

  const match = NAV_ITEMS.filter((item) => item.href !== '/')
    .filter((item) => pathname === item.href || pathname.startsWith(item.href + '/'))
    .sort((a, b) => b.href.length - a.href.length)[0]

  return match?.permission ?? null
}

/**
 * Pages that exist before an operator does.
 *
 * The route guard denies any path NAV does not cover, which is right for a
 * console and wrong for these two: their whole purpose is to be reachable by
 * somebody with no session and no permissions. `/set-password` in particular
 * is opened from a link in a chat by a reseller who has never signed in.
 *
 * One list, because the guard, the shell and the test each have to ask the
 * same question and three answers is how one of them drifts.
 */
export const PUBLIC_ROUTES = ['/sign-in', '/set-password'] as const

export function isPublicRoute(pathname: string): boolean {
  return PUBLIC_ROUTES.some((route) => pathname.startsWith(route))
}

/**
 * Where somebody belongs when they open the panel at `/`.
 *
 * Sign-in sends everyone to the dashboard, which is gated on
 * `analytics.view` - a permission a reseller deliberately does not hold. They
 * signed in successfully and were shown "دسترسی ندارید". The first entry they
 * can actually see is the honest answer, and it is `/portal` for a reseller
 * without naming the role here.
 */
export function landingFor(can: (permission: Permission) => boolean): string {
  if (can('analytics.view')) return '/'
  return NAV_ITEMS.find((item) => item.href !== '/' && can(item.permission))?.href ?? '/'
}
