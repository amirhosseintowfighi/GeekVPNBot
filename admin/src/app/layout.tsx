import type { Metadata, Viewport } from 'next'
import { Vazirmatn } from 'next/font/google'

import { Providers } from './providers'
import { AppShell } from '@/components/shell/app-shell'
import './globals.css'

const vazirmatn = Vazirmatn({
  subsets: ['arabic'],
  display: 'swap',
  variable: '--font-vazirmatn',
})

export const metadata: Metadata = {
  title: {
    default: '\u067e\u0646\u0644 \u0645\u062f\u06cc\u0631\u06cc\u062a GeekVPN',
    template: '%s | GeekVPN',
  },
  // An admin panel must never be indexed.
  robots: { index: false, follow: false, nocache: true },
}

export const viewport: Viewport = {
  themeColor: '#0e1013',
  width: 'device-width',
  initialScale: 1,
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // dir="rtl" is what makes every logical Tailwind property resolve
    // correctly. The `dark` class is permanent: there is no light theme to
    // toggle to, so there is no flash-of-wrong-theme script either.
    <html lang="fa" dir="rtl" className={`dark ${vazirmatn.variable}`}>
      <body className="min-h-dvh bg-background font-sans antialiased">
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  )
}
