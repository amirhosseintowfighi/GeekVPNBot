# \u0642\u0631\u0627\u0631\u062f\u0627\u062f API

Everything the panel needs from the backend, as consumed by `src/lib/api.ts`.
Base: `NEXT_PUBLIC_ADMIN_API_URL` + `/api/admin`.

## Conventions

- Session is an **httpOnly cookie**; every request sends
  `credentials: 'include'` and `cache: 'no-store'`.
- Every mutation sends `Idempotency-Key: <uuid>`. The backend must dedupe on
  it. Approving the same payment twice is a real refund.
- `401` \u2192 the panel re-checks the session and redirects to `/sign-in`.
  `403` \u2192 Persian forbidden state. `204` \u2192 `undefined`.
- Errors return `{ messageFa }`. **The backend owns the Persian error text**;
  the panel never invents one. A network failure is surfaced as status `0`
  with a generic offline message.
- List endpoints take `{ page, pageSize, q, sort, direction, \u2026filters }` and
  return `{ items, page, pageSize, total }`. Admin `pageSize` is 25.

## Endpoints

```
GET    /session                     POST /sign-out
GET    /dashboard?days=             GET  /analytics?days=
GET    /users                       GET  /users/:id
PATCH  /users/:id                   POST /users/:id/state
GET    /users/:id/subscriptions     POST /subscriptions/:id/rotate
GET    /orders                      GET  /orders/:id
POST   /orders/:id/approve          POST /orders/:id/reject   { reasonFa }
POST   /orders/:id/refund { reasonFa }
GET    /categories                  POST /categories
GET    /products                    POST /products           POST /products/:id/state
GET    /plans                       POST /plans              POST /plans/:id/state
GET    /products/:id/ladder         POST /products/:id/ladder { monthlyPrice }
GET    /panels                      POST /panels
POST   /panels/:id/test             POST /panels/:id/sync
GET    /servers                     POST /servers
GET    /coupons                     POST /coupons
POST   /coupons/bulk { prefix, count, discountBps }  \u2192 { codes }
POST   /coupons/:id/archive
GET    /campaigns                   POST /campaigns          POST /campaigns/:id/state
GET    /broadcasts                  POST /broadcasts/estimate \u2192 { count }
POST   /broadcasts                  POST /broadcasts/send    POST /broadcasts/:id/cancel
GET    /tickets                     GET  /tickets/:id/messages
POST   /tickets/:id/reply           POST /tickets/:id/state
GET    /wallet/transactions         POST /wallet/adjust { userId, amount, reasonFa }
GET    /logs                        GET  /settings           PUT  /settings
GET    /operators                   POST /operators          POST /operators/:id/enabled
```

## Rules the backend must enforce independently

The panel's checks are a courtesy. The server re-validates: RBAC on every
route, the 5-character reason on reject / refund / suspend / wallet
adjustment, the 70% discount ceiling, bulk coupon count \u2264 1000, and quiet
hours 23\u21928 for every broadcast category except CRITICAL.

## Analytics

`GET /analytics?days=<7|30|90|365>` returns one `AnalyticsBundle`. One round
trip on purpose: six independent requests would let the cards and the charts
describe different periods while they load.

Produced by `AnalyticsBundle.as_dict()` in `domain/analytics/dashboard.py`.
The keys below are the contract; the panel's `src/lib/types.ts` mirrors them.

```jsonc
{
  "range":  { "start": "ISO", "end": "ISO", "days": 30,
              "labelFa": "\u06f1\u06f4\u06f0\u06f5/\u06f0\u06f4/\u06f1\u06f4 \u062a\u0627 \u06f1\u06f4\u06f0\u06f5/\u06f0\u06f5/\u06f1\u06f2", "granularity": "day" },

  "metrics": [                       // 8 cards, always in this order
    { "key": "net_revenue", "labelFa": "\u062f\u0631\u0622\u0645\u062f \u062e\u0627\u0644\u0635", "format": "toman",
      "value": 10500000, "previous": 8900000,
      "valueFa": "\u06f1\u06f0\u066c\u06f5\u06f0\u06f0\u066c\u06f0\u06f0\u06f0 \u062a\u0648\u0645\u0627\u0646",
      "changePercent": 17.98,        // null when there is no baseline
      "changeFa": "+\u06f1\u06f7\u066b\u06f1\u066a",       // "\u2014" when null
      "direction": "up",             // up | down | flat
      "isImprovement": true,         // null when flat; already accounts for churn
      "hintFa": "" }
  ],

  "revenueSeries": { "key": "net_revenue", "labelFa": "...", "format": "toman",
                     "granularity": "day", "total": 10500000,
                     "points": [ { "at": "ISO", "value": 350000, "labelFa": "\u06f1\u06f2 \u0645\u0631\u062f\u0627\u062f" } ] },
  "ordersSeries":  { /* same shape, format "count" */ },

  "planBreakdown":   { "key": "...", "labelFa": "...", "format": "toman",
                       "slices": [ { "key": "direct30", "labelFa": "Geek Direct 30",
                                     "value": 12000000, "share": 42.1 } ] },
  "methodBreakdown": { /* same shape, keyed by payment method */ },

  "revenue":   { "gross": 0, "discounts": 0, "refunds": 0, "collected": 0, "net": 0,
                 "walletTopups": 0, "orders": 0, "payingUsers": 0, "newUsers": 0,
                 "aov": 0, "arpu": 0, "discountRate": 0, "refundRate": 0, "netFa": "" },
  "retention": { "renewalRate": 0, "churnRate": 0, "growthRate": 0, "lifetimeValue": 0, "headlineFa": "" },
  "funnel":    { "conversionRate": 0, "steps": [ { "stage": "viewed_shop", "labelFa": "",
                   "count": 0, "stepRate": 0, "overallRate": 0, "dropped": 0, "dropRate": 0 } ] },
  "referral":  { "signups": 0, "converted": 0, "revenue": 0, "totalCost": 0,
                 "netRevenue": 0, "cpa": 0, "roas": 0, "profitable": true },
  "segments":  { "totalCustomers": 0, "winBackAudience": 0,
                 "stats": [ { "kind": "churned", "labelFa": "", "customers": 0,
                              "revenue": 0, "share": 0, "isWinBack": true } ] },
  "traffic":   { "meteredGib": 0, "unlimitedPlans": 0, "usedGib": 0,
                 "utilisation": 0, "summaryFa": "" },
  "fleet":     { "onlineNodes": 0, "totalNodes": 0, "loadPercent": 0,
                 "nodes": [ { "nodeId": "", "name": "", "loadPercent": 0, "healthFa": "" } ],
                 "attention": [ /* same node shape */ ] },
  "cohorts":   { "periods": 3, "cohorts": [ { "key": "1405-04", "labelFa": "\u062a\u06cc\u0631",
                   "size": 140, "cells": [ { "period": 0, "retained": 140, "rate": 100 } ] } ] },

  "campaigns":    [ { "campaignId": "", "nameFa": "", "netRevenue": 0,
                      "discountGiven": 0, "returnOnDiscount": 0 } ],
  "topReferrers": [ { "userId": 0, "displayName": "", "converted": 0,
                      "revenue": 0, "netContribution": 0 } ],
  "topPlans":     [ { "planId": "", "planName": "", "orders": 0, "revenue": 0 } ]
}
```

### Rules

- `format` is one of `toman | count | percent | gib | days` and drives the
  panel's `formatValue`.
- Series always contain **every** bucket in the range, zero-filled. The backend
  must not omit empty days; a chart that skips them draws a smooth line through
  an outage.
- `changePercent` is `null` when the previous period was zero, and the panel
  renders `changeFa` (an em dash) rather than inventing a percentage.
- `isImprovement` already accounts for metrics where lower is better, so the
  `invert` prop the panel passes for `churn` is belt and braces, not the source
  of truth.
- Breakdowns are pre-trimmed to the top 6 with the tail folded into \u0633\u0627\u06cc\u0631.

### Additional endpoints

```
GET /analytics/export?days=<n>     \u2192 text/csv; charset=utf-8
GET /analytics/marketing?days=<n>  \u2192 { suggestions: [\u2026] }
GET /analytics/leaderboard?days=<n>\u2192 { rows: [\u2026] }
```

The CSV body **must** begin with a UTF-8 BOM. Excel on Windows reads a BOM-less
UTF-8 CSV as windows-1256 and turns every Persian heading into mojibake.
Headings are Persian, values are ASCII digits, and the filename is ASCII
(`geekvpn-analytics-30d.csv`) because Persian in `Content-Disposition` needs RFC
5987 and still breaks in older clients.

Permissions: `analytics.view` for the bundle, `analytics.export` for the CSV.

---

## Path alignment decision (2026-08-07)

The panel and the backend had diverged: the client called `/admin/session`,
`/admin/dashboard`, `/admin/categories` and so on, none of which were
registered routes.

**The backend won.** It has tests, two other clients, and an OpenAPI document;
the panel had none of the three. Every path in `src/lib/api.ts` was moved onto
the registered route.

| was | is |
|---|---|
| `/admin/session` | `/admin/auth/me` |
| `/admin/dashboard` | `/admin/analytics/dashboard` |
| `/admin/logs` | `/admin/audit-logs` |
| `/admin/operators` | `/admin/admins` |
| `/admin/users` | `/admin/customers` |
| `/admin/servers` | `/admin/panels` |
| `/admin/categories`, `/products`, `/plans`, `/coupons`, `/campaigns` | the same under `/admin/catalog/` |
| `/admin/panels/{id}/test` | `/admin/panels/{id}/test-connection` |

Three calls changed shape rather than path, because the backend models them
differently and the difference is deliberate:

- `setOperatorEnabled(id, bool)` → `disableOperator(id)`. Disabling is a
  `DELETE` that also ends every session the operator holds, and there is no
  re-enable.
- `setUserState(id, state, reason)` → `suspendUser(id, reason)` /
  `reinstateUser(id)`. A suspension always carries a reason; a reinstatement
  never does, and one function taking an optional reason hid that.
- `setTicketState(id, state)` → `closeTicket(id)`. Closing is the only
  transition exposed as a single call; priority, category and assignment have
  their own routes.

### Enforcement

`tests/integration/test_admin_api_contract.py` extracts every `${ROOT}/…`
literal from `admin/src` and diffs it against `create_app()`'s routes. It fails
on a new mismatch **and** on a `KNOWN_GAPS` entry that has quietly been
implemented, so the exemption list can only shrink.

### Still missing a backend

Listed in `KNOWN_GAPS` with a reason each: broadcasts (4), the duration ladder
(2), nested plan creation, panel account-count resync, subscription link
rotation, admin sign-out, the two wallet routes that need a customer id, and
order approve/reject/refund — the last three because the backend keys those on
a *payment* id while the panel holds an *order* id, which is a contract change
rather than a path edit.
