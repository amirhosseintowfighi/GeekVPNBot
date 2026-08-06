# \u0645\u0639\u0645\u0627\u0631\u06cc \u067e\u0646\u0644 \u0645\u062f\u06cc\u0631\u06cc\u062a

Admin panel for GeekVPN. Next.js App Router, React, TypeScript, Tailwind,
shadcn-style primitives, Recharts. Persian-only, RTL, dark-only.

## Why this is a separate app from the Mini App

The Mini App runs inside Telegram's webview and is *designed* to be framed.
The admin panel must never be framed: `next.config.mjs` sends
`X-Frame-Options: DENY`, `frame-ancestors 'none'`, `nosniff` and
`Referrer-Policy: no-referrer`. These are contradictory requirements, so they
are contradictory deployments. The panel runs on port **3001**.

The two apps also share no session. The Mini App authenticates with Telegram
initData; the panel uses an httpOnly cookie issued to a human operator.

## Layers

```
src/lib          pure logic: fa, jalali, rbac, labels, types, api, nav
src/components/ui        primitives (button, table, dialog, \u2026)
src/components/shell     session, sidebar, topbar, guard, states
src/components/charts    RTL-aware Recharts wrappers
src/components/feature   metric cards, queue tiles
src/app                  one folder per screen
```

Everything under `src/lib` is framework-free and is what the tests exercise.

## RBAC is a courtesy, not a control

`rbac.ts` decides which buttons render. It is duplicated on the server, which
re-checks every request. If the two ever disagree the server wins and the UI
shows a Persian forbidden state. Never treat a hidden button as security.

Five roles: \u0645\u0627\u0644\u06a9 / \u0645\u062f\u06cc\u0631 / \u0645\u0627\u0644\u06cc / \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc / \u0646\u0627\u0638\u0631, 38 permissions.
`canAssignRole` forbids granting a role at or above your own rank, and
forbids granting `owner` to anyone, ever.

## Data fetching

SWR against `src/lib/api.ts`. Every mutation carries
`Idempotency-Key: crypto.randomUUID()`, because approving a payment twice on
a flaky connection is a real refund. `401` bounces to sign-in, `403` renders
the forbidden state, network failure renders an offline state with retry.

## Formatting parity

`fa.ts` and `jalali.ts` are copied verbatim from the Mini App, not
reimplemented. A price shown to an operator and the same price shown to the
customer must be the same string, down to the Persian thousands separator.
Do not "improve" one copy in isolation.
