import type { Metadata, Viewport } from 'next'
import { Vazirmatn } from 'next/font/google'
import Script from 'next/script'

import { BottomNav } from '@/components/shell/bottom-nav'
import { Providers } from './providers'
import './globals.css'

/**
 * Vazirmatn is the de-facto standard Persian UI face and the same family the
 * bot's brand uses. Self-hosting through next/font avoids a render-blocking
 * request to Google on a mobile connection, and `display: swap` means text is
 * readable immediately rather than invisible while the font loads.
 */
const vazirmatn = Vazirmatn({
  subsets: ['arabic'],
  display: 'swap',
  variable: '--font-vazirmatn',
})

export const metadata: Metadata = {
  title: 'GeekVPN',
  description:
    '\u0627\u06cc\u0646\u062a\u0631\u0646\u062a \u0628\u062f\u0648\u0646 \u0645\u0631\u0632\u060c \u0628\u0627 \u06a9\u06cc\u0641\u06cc\u062a \u062d\u0631\u0641\u0647\u200c\u0627\u06cc',
  // The Mini App is opened from Telegram, never found in a search engine.
  robots: { index: false, follow: false },
}

export const viewport: Viewport = {
  themeColor: '#0A0A0F',
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
    <html lang="fa" dir="rtl" className={`dark ${vazirmatn.variable}`}>
      <body className="min-h-dvh bg-background font-sans">
        {/* Telegram does not inject its SDK - the page has to ask for it. Without
            this tag `window.Telegram` is undefined even inside a real Telegram
            client, so `getInitData()` returns an empty string, every request goes
            out unauthenticated and the whole Mini App answers 401. It must load
            before hydration: `initTelegram()` runs in a Providers effect, and an
            effect that fires before the SDK exists silently does nothing. */}
        <Script src="https://telegram.org/js/telegram-web-app.js" strategy="beforeInteractive" />
        <Providers>
          {/* The ambient glow behind the header. Fixed and non-interactive so
              it never intercepts a tap or scrolls out of place. */}
          <div
            className="pointer-events-none fixed inset-x-0 top-0 h-64 glow"
            aria-hidden
          />

          <div className="relative mx-auto flex min-h-dvh w-full max-w-2xl flex-col">
            {/* pb-24 reserves room for the fixed tab bar, so the last card in
                a list is never trapped underneath it. */}
            <main className="safe-top flex-1 px-4 pb-24 pt-2">{children}</main>
            <BottomNav />
          </div>
        </Providers>
      </body>
    </html>
  )
}
