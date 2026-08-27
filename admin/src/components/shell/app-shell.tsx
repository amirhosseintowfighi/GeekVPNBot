'use client'

import * as React from 'react'

import { isPublicRoute } from '@/lib/nav'
import { usePathname } from 'next/navigation'
import useSWR from 'swr'

import { api } from '@/lib/api'
import type { DashboardSummary } from '@/lib/types'
import { Sidebar, SidebarDrawer } from './sidebar'
import { Topbar } from './topbar'
import { RouteGuard } from './guard'

/**
 * The frame every screen renders inside.
 *
 * Responsive strategy in one place:
 * - `lg` and up: permanent 15rem sidebar beside a scrolling content column.
 * - below `lg`: no rail at all, an overlay drawer opened from the topbar.
 *
 * The content column owns its own scroll rather than the document, which is
 * what keeps the sidebar and the sticky table headers fixed while a long list
 * scrolls underneath them.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const [menuOpen, setMenuOpen] = React.useState(false)

  // Sign-in is the one route that renders outside the frame: no navigation to
  // show and no session to read.
  const isBareRoute = isPublicRoute(pathname)

  /*
   * The action queue powers the sidebar badges.
   *
   * Deliberately a short poll rather than a websocket: the numbers only need
   * to be minutes-fresh, and a polling GET degrades gracefully over the
   * flaky connections this panel is often used on. One small endpoint every
   * 60s is cheaper than a connection held open per operator.
   */
  const { data } = useSWR<DashboardSummary>(
    isBareRoute ? null : '/api/admin/dashboard?days=1',
    () => api.dashboard(1),
    { refreshInterval: 60_000, revalidateOnFocus: true },
  )

  if (isBareRoute) return <>{children}</>

  const queue = data?.actions ?? null

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar queue={queue} />
      <SidebarDrawer open={menuOpen} onClose={() => setMenuOpen(false)} queue={queue} />

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenMenu={() => setMenuOpen(true)} />

        <main className="min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-5 sm:py-5">
          {/* max-w keeps line lengths sane on an ultrawide monitor without
              capping tables so tightly that columns start truncating. */}
          <div className="mx-auto w-full max-w-[1600px]">
            <RouteGuard>{children}</RouteGuard>
          </div>
        </main>
      </div>
    </div>
  )
}
