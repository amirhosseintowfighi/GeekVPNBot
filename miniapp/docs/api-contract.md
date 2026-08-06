# API contract

Every endpoint the Mini App calls. None of these exist yet; they are the
remaining backend work.

## Conventions

- Base path: `/api/miniapp`
- Auth header on every request: `Authorization: tma <initData>`
- The server must re-verify `initData` by HMAC against the bot token on every
  request. Never trust a user id sent in a body.
- All money is an integer count of tomans.
- All timestamps are ISO-8601 strings in UTC.
- All display strings arrive already in Persian, suffixed `Fa`. The client
  never translates.
- Errors return a JSON body with a `messageFa` the client may render verbatim.

| Status | Client behaviour |
| --- | --- |
| 401 | Session invalid; the customer is asked to reopen from the bot |
| 402 | Insufficient wallet balance |
| 409 | Conflict, e.g. plan no longer published |
| 422 | Validation, e.g. coupon rejected |
| 429 | Rate limited |
| 5xx | Generic Persian error, retried once |

## Catalog and checkout

| Method | Path | Returns | Backed by |
| --- | --- | --- | --- |
| GET | `/storefront` | `Storefront` | `StorefrontService` |
| POST | `/quote` | `Quote` | `QuotingService` |
| POST | `/coupon/preview` | `CouponPreview` | `QuotingService` |
| POST | `/checkout/wallet` | `{ subscriptionId }` | `CheckoutService.pay_from_wallet` |
| POST | `/checkout/card` | `PendingPayment` | `CheckoutService.begin_card` |
| POST | `/checkout/crypto` | `PendingPayment` | `CheckoutService.begin_crypto` |

`/quote` and `/coupon/preview` differ in one way that matters: a rejected
coupon is a 200 with `accepted: false` on the preview endpoint, because the
customer typing a wrong code is an expected outcome, not an error.

## Payments

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/payments/pending` | `PendingPayment[]` |
| POST | `/payments/:id/receipt` | 204 |
| POST | `/payments/:id/txid` | 204 |

The receipt endpoint exists for completeness; the Mini App deliberately sends
customers to the bot to upload an image.

State machine: `draft` to `awaiting_proof` to `pending_review` to `approved`
or `rejected`, with `expired` reachable from anything unsettled. The client
polls this screen every 15 seconds and redirects on `approved`.

## Subscriptions

| Method | Path | Returns | Backed by |
| --- | --- | --- | --- |
| GET | `/subscriptions` | `SubscriptionCard[]` | `SubscriptionReader.list_for_user` |
| POST | `/subscriptions/:id/rotate` | `{ subscriptionUrl }` | `SubscriptionReader.rotate_link` |
| GET | `/subscriptions/:id/renewal-options` | `Storefront` | catalog filtered to the product |

Renewal options return a full `Storefront` so the renew screen can reuse
`PlanCard` and hand off to the ordinary checkout. Quoting stays in one place.

## Wallet

| Method | Path | Returns | Backed by |
| --- | --- | --- | --- |
| GET | `/wallet` | `WalletSnapshot` | `WalletReader.snapshot` |
| GET | `/wallet/transactions?page=&page_size=` | `{ items, total }` | `WalletReader.transactions` |
| POST | `/wallet/topup` | `PendingPayment` | `CheckoutService.begin_topup` |

Top-up bounds are enforced server-side: minimum 50,000 and maximum 50,000,000
tomans. The client duplicates them only to disable the button early.

## Everything else

| Method | Path | Returns | Backed by |
| --- | --- | --- | --- |
| GET | `/referral` | `ReferralSummary` | `ReferralReader.summary` |
| GET | `/profile` | `ProfileSummary` | `ProfileReader.summary` |
| PATCH | `/profile` | `ProfileSummary` | `ProfileReader.set_display_name` |
| GET | `/preferences` | `NotificationPreferences` | `PreferencesStore.load` |
| PUT | `/preferences` | `NotificationPreferences` | `PreferencesStore.save` |
| GET | `/tickets` | `TicketCard[]` | `TicketReader.list_for_user` |
| POST | `/tickets` | `TicketCard` | `TicketReader.open_ticket` |
| GET | `/tickets/:id/messages` | `TicketMessage[]` | ticket thread |
| POST | `/tickets/:id/messages` | `TicketMessage` | ticket reply |
| GET | `/servers` | `ServerStatusRow[]` | `ServerStatusReader.rows` |
| GET | `/faq` | `FaqSection[]` | `faq_content` |

The notification preference payload has no `critical` key. Critical notices
bypass preferences and quiet hours entirely, so offering a switch for them
would be a lie.

## Things the API must never expose

- Any panel credential, inbound id, or node hostname.
- Another customer's referral attribution.
- Raw internal error text.
- A price the client is expected to compute. Every total on a screen was
  calculated by `QuotingService`.
