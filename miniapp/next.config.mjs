/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  // The Mini App runs inside Telegram's in-app webview, served from Telegram's
  // own origin. Framing must therefore be allowed - but only by Telegram. A
  // bare ALLOWALL would make the whole wallet clickjackable from any site.
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          {
            key: 'Content-Security-Policy',
            value:
              'frame-ancestors https://web.telegram.org https://*.telegram.org',
          },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
        ],
      },
    ]
  },
}

export default nextConfig
