import {
  BadgePercent,
  Boxes,
  ChartNoAxesCombined,
  FileClock,
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
}

export interface NavSection {
  titleFa: string
  items: NavItem[]
}

export const NAV: NavSection[] = [
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
        href: '/orders',
        labelFa: '\u0633\u0641\u0627\u0631\u0634\u200c\u0647\u0627',
        icon: Receipt,
        permission: 'orders.read',
        queueKey: 'pending_payments',
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
