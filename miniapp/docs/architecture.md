# Architecture

## The shape of it

```
Telegram client
      |  initData (signed, HMAC over the bot token)
      v
Mini App (Next.js, this package)
      |  Authorization: tma <initData>
      v
FastAPI  /api/miniapp/*        <-- thin translation layer, still to be written
      |
      v
StorefrontService, QuotingService, BotServices (8 ports)
      |
      v
Domain: catalog, pricing, wallet, referral
```

The Mini App is a second **presentation** layer over the same application
services the bot uses. It is not a second product. Every number it shows has
already been decided by the domain, and nothing here recomputes a price.

## Why the API client is one file

`src/lib/api.ts` is the only module that calls `fetch`. Three things are
decided there once instead of at forty call sites:

1. **Auth.** Every request carries `initData`. There is no session cookie and
   no client-held token, so there is nothing for a malicious page to steal.
2. **Error shaping.** A failure becomes an `ApiError` with a `messageFa` that
   is safe to render. A raw 500 or a stack trace can never reach a screen.
3. **Offline.** A network failure is `status: 0` with its own Persian message,
   because "check your connection" and "something broke on our side" send the
   customer to two different places.

## Data fetching

SWR, with three settings that matter:

- `revalidateOnFocus: true`. The customer leaves to make a card transfer and
  comes back; that is exactly the moment payment state changes.
- `dedupingInterval: 5000`. The home screen asks for the wallet, and so does
  the checkout screen. One request.
- `shouldRetryOnError` only for `status === 0` or `>= 500`. Retrying a 400 just
  repeats a rejection the customer already saw.

Mutations follow one of two patterns:

- **Optimistic** where the failure is cheap and reversible - the settings
  toggles. The switch moves immediately and rolls back with a message.
- **Pessimistic** everywhere money or access is involved - checkout, top-up,
  link rotation. The server's answer is the only truth worth rendering.

## Types

`src/lib/types.ts` mirrors `application/bot/read_models.py` by hand. No
generator. The read models are stable and change about once per phase, so a
generator would buy a build step and a toolchain in exchange for very little.

Two invariants carried over from Python:

- **Money is an integer count of tomans.** Never a float. Iranian prices run
  into the millions and a float rounding error in a wallet balance is not
  cosmetic.
- **Timestamps are ISO strings**, parsed at the edge by `fa.ts`. No component
  wonders whether it is holding a string or a `Date`.

## Mirrored logic, and why duplication is accepted here

A few rules exist in both Python and TypeScript:

| Rule | Python home | TS home |
| --- | --- | --- |
| `is_renewable` excludes `suspended` | `read_models.py` | `subscription-card.tsx` |
| `is_credit` for topup/cashback/referral/refund | `read_models.py` | `wallet/page.tsx` |
| Quota warning thresholds 0.75 / 0.90 | notifier | `progress.tsx` |
| Top-up bounds and presets | wallet handler | `wallet/topup/page.tsx` |
| Loyalty tier thresholds | `handlers/common.py` | `profile/page.tsx` |

Each of these decides what the *interface* offers, not what the system
permits. The backend enforces all of them again. The duplication is a
liability, and `tests/usage-tone.test.ts` exists specifically to make one of
the drifts loud.

## Rendering strategy

Almost every screen is a client component, because almost every screen is
personalised and authenticated by a token that only exists in the browser.
Server rendering the shell still pays for itself: the layout, fonts, theme and
tab bar arrive as HTML while the data is in flight.

Nothing is statically generated. There is no page here that is the same for
two customers.

## Motion

`src/lib/motion.ts` holds one easing curve and a small set of variants. Rules:

- Nothing runs longer than 300ms.
- Animate `transform` and `opacity` only, so work stays on the compositor.
  The progress bar fills with `translateX`, not `width`.
- `MotionConfig reducedMotion="user"` is set globally, so the OS setting is
  respected without a check in every component.

## Where a payment gateway will slot in

`CheckoutService` in the bot already abstracts payment initiation. Adding a
gateway means one more method there, one more `MethodOption` on the checkout
screen, and one more branch on the payment screen. The `PaymentState` machine
already has `approved` and `rejected`; an instant gateway simply reaches them
without passing through `pending_review`.
