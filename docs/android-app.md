# Android app: shop additions

The app signs in as described in `authentication.md` and then uses the Mini
App routes (`/api/miniapp/*`) with a Bearer token. Three things exist only for
the app; the owner controls at the end are the bot's own, exposed for it.

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

## Owner controls: devices, name, transfer, refund

The bot's «دستگاه‌های متصل» list and the rename, transfer and refund buttons on
a service. Each endpoint calls what the bot's handler calls -
`AppLinkLogin.devices/disconnect` and `BotServiceOwnership.rename/transfer/
refund_quote/refund_unused` - so the shop's switches, the ownership check, the
message to a recipient and the operators' report are the bot's. A change made
through the API adds `از طریق: اپ` (Bearer) or `از طریق: مینی‌اپ` (initData) to
that report.

Errors are the usual problem body; `title` is the code below and `message_fa`
is the sentence to show. A service or device that is not the caller's is the
same 404 as one that does not exist.

| Method and path | Body | Success |
| --- | --- | --- |
| `GET /devices` | - | 200 `Device[]`, most recently used first |
| `POST /devices/{deviceId}/revoke` | - | 204 |
| `POST /subscriptions/{id}/name` | `{"name": string \| null}` | 200 `SubscriptionCard` |
| `POST /subscriptions/{id}/transfer` | `{"recipient": string \| number}` | 200 `Transfer` |
| `GET /subscriptions/{id}/refund` | - | 200 `RefundOffer` |
| `POST /subscriptions/{id}/refund` | - | 200 `RefundDone` |

`Device`: `deviceId` (uuid, the app session), `name`, `platform` (nullable),
`appVersion` (nullable), `createdAt`, `lastSeenAt`, `current` (the session of
the token that asked; always false with initData). Only sessions from the two
app sign-ins are devices, as in the bot. `platform` and `appVersion` are read
back from the session's `GeekVPN/<version> (<platform>)` user agent and are null
when it says anything else. Revoking ends the session, its refresh tokens and
its access tokens at once, so the device's next refresh is refused; a device may
revoke itself.

Name: `null`, blank or a lone `-` clears it. Whitespace is squeezed; at most 32
characters after that. The name is the card's existing `displayName`, which is
only ours: the panel account and the config's remark are not changed.

Transfer: the recipient is a numeric Telegram id (Persian digits accepted),
as the bot asks. They must have started this shop's bot. The move is immediate
and the customer cannot undo it, so the app draws the confirmation the bot
draws. The panel account is untouched (same link, same traffic, same date) and
auto-renewal is switched off. The recipient gets the bot's Telegram message.

Refund: only an active, paid (not trial) service with no traffic, within the
shop's `services.refund_window_hours` of purchase. It is immediate and goes to
the wallet - the bot has no request for an operator to approve, no card payout
and no reason field. The panel account is deleted first. `GET` checks the
stored traffic counter, as the bot does to show its button; `POST` asks the
panel, so it can still answer `refund_service_used`.

| `title` | HTTP | Where |
| --- | --- | --- |
| `device_not_found` | 404 | revoke |
| `subscription_not_found` | 404 | name, transfer, refund |
| `feature_disabled` | 409 | name, transfer |
| `subscription_revoked` | 409 | name, transfer |
| `service_name_too_long` | 422 | name |
| `transfer_recipient_invalid` | 422 | transfer |
| `transfer_to_self` | 422 | transfer |
| `transfer_recipient_not_found` | 422 | transfer |
| `refund_disabled`, `refund_service_not_active`, `refund_window_closed`, `refund_not_purchased`, `refund_service_used`, `unused_refund_refused` | 409 | `POST` refund; the same codes are `reasonCode` on `GET` |
| `validation_error` | 422 | a body that does not match |
