'use client'

import { MotionConfig } from 'framer-motion'
import { SWRConfig } from 'swr'
import { useEffect } from 'react'

import { fetcher } from '@/lib/api'
import { initTelegram } from '@/lib/telegram'

/**
 * Client-side providers.
 *
 * SWR is configured once here rather than per hook. The defaults are chosen
 * for a webview that gets suspended and resumed constantly:
 *
 * - `revalidateOnFocus` is on, because coming back from the Telegram chat
 *   after a card transfer is exactly when a payment status may have changed.
 * - `dedupingInterval` is generous, so bouncing between tabs does not fire the
 *   same request four times over a mobile connection.
 * - Retries are capped. On a dead network, retrying forever drains the battery
 *   and never succeeds; the error state is more useful than a spinner.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    initTelegram()
  }, [])

  return (
    <SWRConfig
      value={{
        fetcher,
        revalidateOnFocus: true,
        revalidateOnReconnect: true,
        dedupingInterval: 5_000,
        errorRetryCount: 3,
        errorRetryInterval: 3_000,
        // 4xx means the request was wrong, not unlucky. Retrying a rejected
        // coupon or a 403 just wastes the customer's data.
        shouldRetryOnError: (error: unknown) => {
          const status = (error as { status?: number })?.status ?? 0
          return status === 0 || status >= 500
        },
      }}
    >
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </SWRConfig>
  )
}
