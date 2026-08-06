'use client'

import * as React from 'react'
import { SWRConfig } from 'swr'

import { ApiError, fetcher } from '@/lib/api'
import { TooltipProvider } from '@/components/ui/primitives'
import { SessionProvider } from '@/components/shell/session'

/**
 * Global data-fetching policy. The defaults matter more here than in the Mini
 * App, because an operator keeps this panel open in a background tab for a
 * whole shift and then returns to it expecting the truth.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig
      value={{
        fetcher,

        // Returning to the tab is exactly when a stale queue count is
        // dangerous.
        revalidateOnFocus: true,
        revalidateOnReconnect: true,

        // The dashboard and the sidebar both read the action queue. One
        // request, not two.
        dedupingInterval: 5000,

        // Never retry a 4xx. A 403 will still be a 403 on the fourth attempt,
        // and hammering an endpoint that is deliberately refusing is how a
        // rate limiter gets tripped for the whole team.
        shouldRetryOnError: (error: unknown) => {
          if (!(error instanceof ApiError)) return false
          return error.status === 0 || error.status >= 500
        },
        errorRetryCount: 2,
        errorRetryInterval: 3000,

        // Keep the previous page of a table on screen while the next loads,
        // so pagination does not flash an empty body between clicks.
        keepPreviousData: true,
      }}
    >
      <SessionProvider>
        <TooltipProvider delayDuration={300}>{children}</TooltipProvider>
      </SessionProvider>
    </SWRConfig>
  )
}
