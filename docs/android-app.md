# Android app: shop additions

The app signs in as described in `authentication.md` and then uses the Mini
App routes (`/api/miniapp/*`) with a Bearer token. Three things exist only for
the app.

## Free trial

`GET /api/miniapp/trial` answers `{available, trafficMib, durationDays}`.
`POST /api/miniapp/trial` claims it and answers `{subscriptionIds, pending}`.

- Once per customer (Telegram id), recorded in `free_trial_claims`. The
  primary key decides a race; a second claim is 409
  `free_trial_already_claimed`.
- One 50 MiB, 2-day, single-device service per tier: `tunnel` and `direct`.
  Each is an ordinary order (`source = trial`, total 0) filed under the
  shortest published plan of the featured, then first, product of that tier,
  so the service carries the right tier and goes through normal provisioning.
  A tier with nothing published is skipped; with neither tier, 409
  `free_trial_unavailable` and nothing is claimed.
- The claim and the paid orders are committed before any panel is called. A
  panel that fails leaves the order FAILED for the retry queue and is counted
  in `pending`; the customer is not charged a second claim.
- Trial orders do not count as a completed order, so they do not cost the
  customer their first-purchase price or count as a referral conversion.
- The sizes are constants in `application/provisioning/free_trial.py`.

## Receipt photo

`POST /api/miniapp/payments/{id}/receipt-photo`, body = the image, header
`Content-Type: image/jpeg|image/png|image/webp`, at most 8 MiB.

Receipts are Telegram files: operators review them in the bot and the proof
records the file id. So the API sends the photo to the customer's own chat
with this shop's bot (they get a copy and a line saying it is under review),
takes the file id Telegram returns, and calls the same `attach_receipt` a
photo sent in the chat uses. The fingerprint is taken from the bytes
downloaded back from Telegram, as in the bot, so the duplicate-receipt check
covers both paths. The payment must be the customer's and awaiting proof
(404 otherwise), checked before anything is sent.

## Back from the gateway

`/checkout/gateway` and a gateway `/wallet/topup` return `paymentId` with the
link. When the caller used a Bearer token (only the app does), the payment is
remembered in the cache for a day. The `/pay/callback/{id}` page for such a
payment says "برگرد به اپ" and links to
`geekvpn://payment/result?payment=<id>&result=ok|pending|failed|unknown`
(with an automatic redirect, and a button for browsers that block it). The
result in the link is only a hint; the app re-reads its wallet and services.
