'use client'

import * as React from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { X } from 'lucide-react'

import { NAV } from '@/lib/nav'
import { can } from '@/lib/rbac'
import { faNumber } from '@/lib/fa'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useSession } from './session'
import type { ActionItem } from '@/lib/types'

/**
 * Navigation.
 *
 * Responsive strategy: the sidebar is a permanent 15rem rail from `lg` up,
 * and an overlay drawer below it. There is no collapsed icon-only mode - a
 * rail of unlabelled icons in a panel with fifteen destinations is a memory
 * test, and the space saved is not needed on a screen wide enough to show it.
 *
 * Items the operator's role cannot reach are removed, not disabled. A
 * disabled row invites a support message asking why it is grey.
 */

function isActivePath(pathname: string, href: string): boolean {
  if (href === '/') return pathname === '/'
  return pathname === href || pathname.startsWith(href + '/')
}

function NavList({
  queue,
  onNavigate,
}: {
  queue: ActionItem[] | null
  onNavigate?: () => void
}) {
  const pathname = usePathname()
  const { session } = useSession()
  const held = session?.permissions ?? null

  return (
    <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-4">
      {NAV.map((section) => {
        const visible = section.items.filter((item) => can(held, item.permission))
        if (visible.length === 0) return null

        return (
          <div key={section.titleFa} className="space-y-1">
            <p className="px-2 text-2xs font-medium uppercase tracking-wide text-muted-foreground/70">
              {section.titleFa}
            </p>

            {visible.map((item) => {
              const active = isActivePath(pathname, item.href)
              // The dashboard returns only the rows with work on them, so a missing
              // key means zero rather than an error.
              const count =
                (item.queueKey && queue?.find((action) => action.key === item.queueKey)?.count) || 0
              const Icon = item.icon

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={onNavigate}
                  aria-current={active ? 'page' : undefined}
                  className={cn(
                    'flex items-center gap-2.5 rounded-md px-2 py-1.5 text-xs transition-colors',
                    active
                      ? 'bg-primary/15 font-medium text-primary'
                      : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                  )}
                >
                  <Icon className="size-4 shrink-0" aria-hidden />
                  <span className="flex-1 truncate">{item.labelFa}</span>

                  {/*
                    A queue count only appears when there is work waiting.
                    A permanent zero badge trains the eye to ignore the spot
                    where the real number will later appear.
                  */}
                  {count > 0 ? (
                    <span className="nums rounded-full bg-warning/20 px-1.5 py-0.5 text-2xs font-medium text-warning">
                      {faNumber(count)}
                    </span>
                  ) : null}
                </Link>
              )
            })}
          </div>
        )
      })}
    </nav>
  )
}

function Brand() {
  return (
    <div className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-4">
      <span className="grid size-7 place-items-center rounded-md bg-primary/15 text-sm">
        {'\u26a1'}
      </span>
      <div className="min-w-0">
        <p className="truncate text-xs font-semibold">GeekVPN</p>
        <p className="truncate text-2xs text-muted-foreground">
          {'\u067e\u0646\u0644 \u0645\u062f\u06cc\u0631\u06cc\u062a'}
        </p>
      </div>
    </div>
  )
}

export function Sidebar({ queue }: { queue: ActionItem[] | null }) {
  return (
    <aside className="hidden w-60 shrink-0 flex-col border-e border-border bg-sidebar lg:flex">
      <Brand />
      <NavList queue={queue} />
    </aside>
  )
}

/**
 * The mobile drawer.
 *
 * Deliberately not a Radix Dialog: it needs to sit under the topbar's own
 * focus management and close on route change, which is simpler to reason
 * about with a plain overlay than with a modal that traps focus.
 */
export function SidebarDrawer({
  open,
  onClose,
  queue,
}: {
  open: boolean
  onClose: () => void
  queue: ActionItem[] | null
}) {
  const pathname = usePathname()

  // Close on navigation. Without this the drawer stays open over the page the
  // operator just asked for.
  React.useEffect(() => {
    onClose()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname])

  React.useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <button
        type="button"
        aria-label={'\u0628\u0633\u062a\u0646 \u0645\u0646\u0648'}
        onClick={onClose}
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
      />
      <div className="absolute inset-y-0 start-0 flex w-64 flex-col border-e border-border bg-sidebar shadow-2xl animate-fade-in">
        <div className="flex items-center justify-between border-b border-border pe-2">
          <div className="flex-1">
            <Brand />
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label={'\u0628\u0633\u062a\u0646'}>
            <X />
          </Button>
        </div>
        <NavList queue={queue} onNavigate={onClose} />
      </div>
    </div>
  )
}
