# GeekVPN Mini App

A Telegram Mini App that mirrors the whole Telegram bot: shop, checkout,
subscriptions, renewal, wallet, referral, support, profile, settings, FAQ and
server status.

Persian throughout, right-to-left, dark theme only.

---

## Status: not yet run

This code has never been installed, type-checked, built or executed. The
sandbox it was written in has no Node.js. **Do not treat it as working until
the checks below pass on your machine.**

```bash
cd miniapp
npm install
npm run typecheck   # expect to fix a handful of things on the first pass
npm run test
npm run dev
```

The most likely first-run failures are missing `lucide-react` icon names and
small type mismatches at the SWR boundaries. Neither is structural.

---

## Stack, and why

| Choice | Reason |
| --- | --- |
| Next.js 14 (App Router) | Server components for the shell, client components for anything holding state. Route-level code splitting matters on a mobile connection. |
| TypeScript, `strict` + `noUncheckedIndexedAccess` | The data contract with the backend is hand-written; strictness is what keeps it honest. |
| Tailwind | Logical properties (`ps`, `pe`, `start`, `end`) resolve from `dir="rtl"`, so RTL needs no mirrored stylesheet. |
| shadcn/ui + Radix | Accessible primitives that are copied into the repo, so RTL fixes can be made in place instead of fought with. |
| Framer Motion | Shared-layout transitions for the tab indicator. Nothing animates longer than 300ms. |
| SWR | Cache plus revalidate-on-focus, which is the behaviour that matters when someone leaves to make a card transfer and comes back. |

---

## Layout of the code

```
src/
  app/
    layout.tsx            html[lang=fa][dir=rtl].dark, Vazirmatn, shell, tab bar
    providers.tsx         SWR + MotionConfig
    page.tsx              home
    shop/                 catalog, then [planId] checkout
    payments/[paymentId]/ card details / crypto address, proof, polling
    services/             subscriptions, then [id]/renew
    wallet/               balance + history, then topup
    referral/  support/   support has a [ticketId] thread
    profile/  settings/  faq/  status/
  components/
    ui/                   shadcn primitives, RTL-corrected
    shell/                page header, tab bar, empty/error/stagger states
    feature/              plan card, subscription card, price breakdown
  lib/
    fa.ts                 TS twin of the bot's ui/fa.py
    jalali.ts             hand-written port of the bot's calendar
    types.ts              mirror of application/bot/read_models.py
    api.ts                the only place that talks HTTP
    telegram.ts           defensive wrapper over the Telegram SDK
    motion.ts             shared easing and variants
tests/                    vitest
```

Further reading in `docs/`:

- `docs/architecture.md` - data flow, why the API client is centralised
- `docs/rtl-persian.md` - the RTL and Persian rules, and the traps
- `docs/api-contract.md` - every endpoint the app expects
- `docs/deployment.md` - env vars, CSP, hosting

---

## Decisions worth arguing with

**Cashback is disclosed but never subtracted.** The backend returns
`cashbackAmount` alongside a total that does not include it, because the money
arrives in the wallet after the order settles. `PriceBreakdown` renders it
below the total, visually detached. Folding it in would show a number that
does not match what the customer types into their banking app.

**Receipt images are uploaded in the bot, not here.** The payment screen shows
the card details and then hands off to the chat. A Mini App cannot put a file
into Telegram's storage without its own upload endpoint and scanning, and the
bot already has a reviewed path for it. The button says so plainly.

**Five tabs.** Support, FAQ, settings, status and referral sit one level down
under Profile, matching the bot's menu. A sixth tab makes every target too
narrow for a thumb.

**No light theme.** Two sets of contrast decisions to maintain for an audience
that opens this inside a dark chat client.

**The Jalali calendar is ported, not imported.** A second implementation can
drift from the bot's, and then chat and app disagree about an expiry date.
`tests/jalali.test.ts` pins it to the same anchors as the Python suite.

**Client-side limits are duplicated deliberately.** `MIN_TOPUP`, `MIN_TXID`,
`MIN_MESSAGE`, `PAGE_SIZE` are copied from the bot's handlers. They gate the
button, not the transaction; the backend remains the authority.

---

## Security

- Auth is the raw Telegram `initData` string, sent as `Authorization: tma ...`
  and re-verified against the bot token on **every** request. `initDataUnsafe`
  is never used for identity.
- The bot token must never carry a `NEXT_PUBLIC_` prefix.
- `next.config.mjs` restricts `frame-ancestors` to Telegram origins rather than
  allowing any framer. An unrestricted Mini App is clickjackable, and this one
  has a wallet in it.

---

## Backend still to build

The routes in `docs/api-contract.md` do not exist yet. They are a thin
translation layer over services that are already written: `StorefrontService`,
`QuotingService`, and the eight `BotServices` ports. No new business logic
belongs in them.
