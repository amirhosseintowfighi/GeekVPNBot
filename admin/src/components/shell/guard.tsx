'use client'

import { usePathname } from 'next/navigation'

import { isPublicRoute, landingFor, permissionForPath } from '@/lib/nav'
import { SkeletonCards } from '@/components/ui/skeleton'
import { ErrorState, ForbiddenState } from './states'
import { useSession } from './session'

/**
 * Route-level permission guard.
 *
 * Resolves the required permission from the navigation table, so a screen is
 * protected the moment it is added to `NAV` - there is no second list to
 * forget. This is a courtesy layer: it spares an operator a screen whose
 * every request would 403. It is not what keeps the data safe.
 */
export function RouteGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const { loading, error, role, can } = useSession()

  if (loading) {
    return (
      <div className="space-y-4">
        <SkeletonCards count={4} />
      </div>
    )
  }

  // A 401 means the cookie is gone or expired. Send the operator to sign in
  // rather than rendering a panel full of failing requests.
  if (error?.status === 401 || !role) {
    if (typeof window !== 'undefined' && !isPublicRoute(pathname)) {
      window.location.href = '/sign-in'
    }
    return null
  }

  if (error) {
    return (
      <ErrorState
        messageFa={error.messageFa}
        offline={error.status === 0}
        onRetry={() => window.location.reload()}
      />
    )
  }

  const required = permissionForPath(pathname)

  // An unmapped route is denied, not allowed. A screen missing from the
  // navigation table is a bug to fix, not a door to leave open.
  if (!required) return <ForbiddenState />

  // Sign-in drops everybody on `/`. Somebody who cannot read the dashboard
  // still has a home - send them there rather than greeting them with a denial
  // on the first screen after a successful login.
  if (pathname === '/' && !can(required)) {
    const home = landingFor(can)
    if (home !== '/' && typeof window !== 'undefined') {
      window.location.href = home
      return null
    }
  }

  if (!can(required)) return <ForbiddenState permission={required} />

  return <>{children}</>
}
