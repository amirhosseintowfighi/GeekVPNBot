'use client'

import * as React from 'react'
import { LogOut, Menu, RefreshCw } from 'lucide-react'

import { api } from '@/lib/api'
import { faRelative } from '@/lib/fa'
import { ROLE_LABEL_FA } from '@/lib/rbac'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useSession } from './session'

/**
 * The topbar carries three things and nothing else: the drawer toggle on
 * small screens, a refresh, and who you are signed in as.
 *
 * The role badge is always visible on purpose. An operator who has forgotten
 * they are in a limited role reads a missing button as a bug; a visible
 * "finance" pill answers the question before it is asked.
 */
export function Topbar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const { session } = useSession()
  const [signingOut, setSigningOut] = React.useState(false)

  const signOut = async () => {
    setSigningOut(true)
    try {
      await api.signOut()
    } catch {
      // Even a failed sign-out sends the operator away. The cookie may already
      // be gone server-side, and leaving them on an authenticated-looking
      // screen is the worse outcome.
    } finally {
      window.location.href = '/sign-in'
    }
  }

  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b border-border bg-background/85 px-3 backdrop-blur sm:px-4">
      <Button
        variant="ghost"
        size="icon"
        className="lg:hidden"
        onClick={onOpenMenu}
        aria-label={'\u0645\u0646\u0648'}
      >
        <Menu />
      </Button>

      <div className="flex-1" />

      <Button
        variant="ghost"
        size="icon"
        onClick={() => window.location.reload()}
        aria-label={'\u0628\u0647\u200c\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06cc'}
      >
        <RefreshCw />
      </Button>

      {session ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" className="gap-2">
              <span className="grid size-6 place-items-center rounded-full bg-primary/15 text-2xs font-semibold text-primary">
                {session.username.trim().charAt(0) || '?'}
              </span>
              <span className="hidden max-w-32 truncate sm:inline">{session.username}</span>
              <Badge variant="outline" className="hidden md:inline-flex">
                {ROLE_LABEL_FA[session.role]}
              </Badge>
            </Button>
          </DropdownMenuTrigger>

          <DropdownMenuContent align="end" className="min-w-56">
            <DropdownMenuLabel>
              <span className="block text-xs font-medium text-foreground">{session.username}</span>
              {/* An operator signs in with a username and a password; there is
                  no Telegram identity on this account at all. */}
            </DropdownMenuLabel>

            <DropdownMenuSeparator />

            <div className="px-2 py-1.5 text-2xs text-muted-foreground">
              {'\u0646\u0642\u0634: ' + ROLE_LABEL_FA[session.role]}
            </div>

            {session.lastLoginAt ? (
              <div className="px-2 pb-1.5 text-2xs text-muted-foreground">
                {'\u0622\u062e\u0631\u06cc\u0646 \u0648\u0631\u0648\u062f: ' + faRelative(session.lastLoginAt)}
              </div>
            ) : null}

            <DropdownMenuSeparator />

            <DropdownMenuItem destructive disabled={signingOut} onSelect={() => void signOut()}>
              <LogOut />
              {'\u062e\u0631\u0648\u062c \u0627\u0632 \u062d\u0633\u0627\u0628'}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </header>
  )
}
