import type { Metadata, Viewport } from 'next'
import Script from 'next/script'

import { SkyBackdrop } from '@/components/brand/sky-backdrop'
import { BottomNav } from '@/components/shell/bottom-nav'
import { THEME_BOOTSTRAP } from '@/lib/shop'
import { Providers } from './providers'
import './globals.css'

export const metadata: Metadata = {
  title: 'GeekVPN',
  description:
    '\u0627\u06cc\u0646\u062a\u0631\u0646\u062a \u0628\u062f\u0648\u0646 \u0645\u0631\u0632\u060c \u0628\u0627 \u06a9\u06cc\u0641\u06cc\u062a \u062d\u0631\u0641\u0647\u200c\u0627\u06cc',
  // The Mini App is opened from Telegram, never found in a search engine.
  robots: { index: false, follow: false },
}

export const viewport: Viewport = {
  // The page blue, so the browser chrome above the app is the same colour.
  themeColor: '#0870D4',
  width: 'device-width',
  initialScale: 1,
  // Pinch-zoom inside a webview usually means the layout broke, and a
  // half-zoomed Mini App has no way to reset itself.
  maximumScale: 1,
  userScalable: false,
  viewportFit: 'cover',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    // `dir="rtl"` on the root is what makes every Tailwind logical property -
    // ps/pe, ms/me, start/end - resolve correctly, which is why the codebase
    // can avoid mirrored stylesheets entirely.
    // Fonts are self-hosted @font-face rules in globals.css (Vazirmatn, with
    // Space Grotesk for Latin figures), not next/font/google: the image is
    // built on a server in Iran, where fetching from Google at build time fails.
    // suppressHydrationWarning: the head script sets `data-theme` on <html>
    // before React hydrates, which React would otherwise report as a mismatch.
    <html lang="fa" dir="rtl" suppressHydrationWarning>
      <head>
        {/* A reseller's shop draws the classic theme, decided before the first
            paint so their customer never sees our blue flash by. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body className="min-h-dvh bg-background font-sans">
        {/* Telegram does not inject its SDK - the page has to ask for it. Without
            this tag `window.Telegram` is undefined even inside a real Telegram
            client, so `getInitData()` returns an empty string, every request goes
            out unauthenticated and the whole Mini App answers 401. It must load
            before hydration: `initTelegram()` runs in a Providers effect, and an
            effect that fires before the SDK exists silently does nothing. */}
        <Script src="https://telegram.org/js/telegram-web-app.js" strategy="beforeInteractive" />
        <Providers>
          <SkyBackdrop />

          <div className="relative mx-auto flex min-h-dvh w-full max-w-2xl flex-col">
            {/* The room under the last card for the floating tab bar is
                reserved by BottomNav itself, which knows when it is shown. */}
            <main className="safe-top flex-1 px-4 pb-6 pt-2">{children}</main>
            <BottomNav />
          </div>
        </Providers>
      </body>
    </html>
  )
}
