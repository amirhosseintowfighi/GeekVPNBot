'use client'

import * as React from 'react'
import useSWR from 'swr'

import { api, ApiError } from '@/lib/api'
import { can, type Permission, type Role } from '@/lib/rbac'
import type { AdminSession } from '@/lib/types'

/**
 * The signed-in operator, fetched once and shared.
 *
 * Every guard in the interface reads from here, so it must never be fetched
 * twice with two different answers. SWR would dedupe on the key, but a
 * context makes the single-source rule explicit and gives the guards a
 * synchronous read.
 *
 * Reminder that cannot be repeated too often: everything this context is used
 * for is cosmetic. The server re-checks every permission on every request.
 */
interface SessionValue {
  session: AdminSession | null
  role: Role | null
  loading: boolean
  /** Null while loading, an ApiError once a load has failed. */
  error: ApiError | null
  can: (permission: Permission) => boolean
  refresh: () => void
}

const SessionContext = React.createContext<SessionValue>({
  session: null,
  role: null,
  loading: true,
  error: null,
  can: () => false,
  refresh: () => {},
})

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const { data, error, isLoading, mutate } = useSWR<AdminSession>(
    '/api/admin/session',
    () => api.session(),
    {
      // The session rarely changes, and a 401 mid-shift should surface as a
      // sign-in prompt rather than a retry storm.
      revalidateOnFocus: false,
      shouldRetryOnError: false,
    },
  )

  const value = React.useMemo<SessionValue>(() => {
    const session = data ?? null
    const role = session?.role ?? null
    // The list the server issued for this operator, which already accounts for
    // any grant or revocation layered on top of their role. Asking the role
    // instead would answer a different question, and answer it from a table
    // this client maintains - the drift that locked every operator out.
    const held = session?.permissions ?? null

    return {
      session,
      role,
      loading: isLoading,
      error: error instanceof ApiError ? error : null,
      // Deny while loading. Rendering a destructive button optimistically and
      // hiding it a moment later is worse than showing it a moment late.
      can: (permission: Permission) => can(held, permission),
      refresh: () => void mutate(),
    }
  }, [data, error, isLoading, mutate])

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionValue {
  return React.useContext(SessionContext)
}

/**
 * Renders children only when the operator holds the permission.
 *
 * Used for buttons and table columns. Route-level protection is handled by
 * the guard in `guard.tsx`, which explains the denial instead of silently
 * rendering nothing.
 */
export function Gate({
  permission,
  fallback = null,
  children,
}: {
  permission: Permission
  fallback?: React.ReactNode
  children: React.ReactNode
}) {
  const { can: allowed } = useSession()
  return <>{allowed(permission) ? children : fallback}</>
}
