/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          // The admin panel must never be framed. Unlike the Mini App, which
          // is designed to live inside Telegram, this surface can suspend an
          // account and move money, so clickjacking it is not survivable.
          { key: 'X-Frame-Options', value: 'DENY' },
          {
            key: 'Content-Security-Policy',
            value: "frame-ancestors 'none'",
          },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          // No referrer at all. An admin URL can contain a user id or an
          // order reference, and neither belongs in someone else's logs.
          { key: 'Referrer-Policy', value: 'no-referrer' },
          {
            key: 'Permissions-Policy',
            value: 'camera=(), microphone=(), geolocation=()',
          },
        ],
      },
    ]
  },
}

export default nextConfig
