# Deployment

## Environment

| Variable | Where | Notes |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | Mini App | Origin of the FastAPI backend. Leave empty to call same-origin. |
| `NEXT_PUBLIC_BOT_USERNAME` | Mini App | Used to build referral deep links. Defaults to `GeekVpnBot`. |
| `TELEGRAM_BOT_TOKEN` | Backend only | Verifies `initData`. Must never carry a `NEXT_PUBLIC_` prefix. |

Anything prefixed `NEXT_PUBLIC_` is compiled into the JavaScript bundle and is
readable by anyone who opens devtools. Only put values there that you would
print on a billboard.

## Build

```bash
cd miniapp
npm ci
npm run typecheck
npm run test
npm run build
npm start
```

Nothing in this package has been executed yet. Expect the first `typecheck`
to surface a handful of fixes.

## Registering the Mini App with Telegram

1. In BotFather: `/newapp`, select the bot, set the HTTPS URL.
2. Add a menu button pointing at the same URL so it opens from the chat.
3. The domain must be HTTPS with a valid certificate. Telegram will not open
   a self-signed origin.

## Headers

`next.config.mjs` sets:

- `frame-ancestors https://web.telegram.org https://telegram.org` - the app is
  designed to be framed, but only by Telegram. Leaving this open makes a
  wallet interface clickjackable.
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`

Do not set `X-Frame-Options: DENY`. It would break the Mini App entirely.

## CORS

If the backend is on a different origin from the app, it must allow that exact
origin, allow the `Authorization` header, and allow `GET, POST, PATCH, PUT`.
Do not use a wildcard origin on an endpoint that accepts credentials.

## Backend checklist before going live

- [ ] `initData` HMAC verified on every request, with an `auth_date` freshness
      window. An unexpired signature replayed a month later is still a valid
      signature unless you check the age.
- [ ] Rate limiting on `/checkout/*`, `/wallet/topup`, and `/tickets`.
- [ ] The same throttle budget as the bot, since both hit the same services.
- [ ] Idempotency on checkout, so a double-tap or a retried request cannot
      create two payments.
- [ ] Structured logs carrying the correlation id the client sends.

## Operational notes

- The payment screen polls every 15 seconds and the status screen every 60.
  Both are cheap reads, but they are the two endpoints that will see the most
  traffic per session; cache them behind a short TTL.
- Card-to-card approval is manual. If the review queue is slow, the customer
  sits on a polling screen watching nothing change. The SLA string shown to
  them comes from the backend, so it can be adjusted without a redeploy.
- When a payment gateway is added later, no route here changes shape. It
  becomes another method on `CheckoutService` and another branch in the
  checkout screen.
