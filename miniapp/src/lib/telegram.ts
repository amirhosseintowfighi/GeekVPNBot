'use client'

/**
 * The bridge to Telegram's WebApp SDK.
 *
 * Everything here is defensive, because the Mini App has to survive three
 * different contexts: a real Telegram client where window.Telegram.WebApp
 * exists, a plain browser during development where it does not, and an older
 * Telegram client where it exists but lacks the newer methods - setHeaderColor
 * and BackButton both shipped later.
 *
 * A missing method degrades to a no-op rather than throwing. A crash inside a
 * webview shows the customer a blank white screen with no way back.
 */

import { useEffect, useState } from 'react'

export interface TelegramUser {
  id: number
  first_name: string
  last_name?: string
  username?: string
  language_code?: string
  photo_url?: string
}

interface HapticFeedback {
  impactOccurred(style: 'light' | 'medium' | 'heavy'): void
  notificationOccurred(type: 'error' | 'success' | 'warning'): void
  selectionChanged(): void
}

interface BackButton {
  show(): void
  hide(): void
  onClick(cb: () => void): void
  offClick(cb: () => void): void
}

export interface TelegramWebApp {
  initData: string
  initDataUnsafe: { user?: TelegramUser; start_param?: string }
  version: string
  colorScheme: 'light' | 'dark'
  viewportStableHeight: number
  isExpanded: boolean
  ready(): void
  expand(): void
  close(): void
  openLink(url: string): void
  openTelegramLink(url: string): void
  setHeaderColor?(color: string): void
  setBackgroundColor?(color: string): void
  HapticFeedback?: HapticFeedback
  BackButton?: BackButton
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp }
  }
}

export function getWebApp(): TelegramWebApp | null {
  if (typeof window === 'undefined') return null
  return window.Telegram?.WebApp ?? null
}

export function isTelegram(): boolean {
  return getWebApp() !== null
}

/**
 * The signed payload proving who the user is.
 *
 * Never trust initDataUnsafe for anything that matters - as the name says, it
 * is unsigned and trivially forged. Only this opaque string, verified
 * server-side against the bot token, establishes identity.
 */
export function getInitData(): string {
  return getWebApp()?.initData ?? ''
}

/** The startapp parameter, which is how a referral link carries its code. */
export function getStartParam(): string | null {
  return getWebApp()?.initDataUnsafe?.start_param ?? null
}

/**
 * Prepare the webview: full height, brand-coloured chrome, ready signal.
 * Optional methods are feature-detected; they arrived in different versions.
 */
export function initTelegram(): void {
  const app = getWebApp()
  if (!app) return

  app.ready()
  app.expand()
  // Match the page background, or the Telegram header sits as a lighter band
  // above a near-black app.
  app.setHeaderColor?.('#0A0A0F')
  app.setBackgroundColor?.('#0A0A0F')
}

/**
 * Haptics. Silent when unsupported, which covers most desktop clients.
 *
 * Used sparingly - a purchase confirmation, a rejected coupon, a tab change.
 * Buzzing on every tap makes an app feel cheap rather than premium.
 */
export const haptic = {
  tap(): void {
    getWebApp()?.HapticFeedback?.impactOccurred('light')
  },
  press(): void {
    getWebApp()?.HapticFeedback?.impactOccurred('medium')
  },
  success(): void {
    getWebApp()?.HapticFeedback?.notificationOccurred('success')
  },
  warning(): void {
    getWebApp()?.HapticFeedback?.notificationOccurred('warning')
  },
  error(): void {
    getWebApp()?.HapticFeedback?.notificationOccurred('error')
  },
  select(): void {
    getWebApp()?.HapticFeedback?.selectionChanged()
  },
}

/**
 * Wire Telegram's native back button to a callback.
 *
 * Telegram draws its own back control in the header; a second in-page arrow
 * beside it looks like a bug. The cleanup path matters - a stale handler left
 * registered navigates somewhere the user has already left.
 */
export function useTelegramBackButton(onBack: (() => void) | null): void {
  useEffect(() => {
    const button = getWebApp()?.BackButton
    if (!button) return

    if (!onBack) {
      button.hide()
      return
    }

    button.onClick(onBack)
    button.show()

    return () => {
      button.offClick(onBack)
      button.hide()
    }
  }, [onBack])
}

/**
 * Open a link outside the webview.
 *
 * Telegram links must go through openTelegramLink or they open a second
 * nested webview instead of switching to the chat - which is exactly what a
 * customer sharing a referral link would hit.
 */
export function openLink(url: string): void {
  const app = getWebApp()
  if (!app) {
    window.open(url, '_blank', 'noopener,noreferrer')
    return
  }
  if (url.startsWith('https://t.me/')) {
    app.openTelegramLink(url)
    return
  }
  app.openLink(url)
}

/**
 * Resolves once the SDK has been detected, or immediately in a browser.
 *
 * Anything that branches on Telegram's presence must wait for this, because
 * the server cannot know whether it exists and would hydrate a mismatch.
 */
export function useTelegramReady(): boolean {
  const [ready, setReady] = useState(false)

  useEffect(() => {
    initTelegram()
    setReady(true)
  }, [])

  return ready
}

/** Copy helper with a haptic tick. Used by card numbers and crypto addresses. */
export async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value)
    haptic.success()
    return true
  } catch {
    haptic.error()
    return false
  }
}
