# GeekVPN \u2014 Admin Panel

Persian, RTL, dark-only control room for the GeekVPN business. Next.js App
Router + React + TypeScript + Tailwind + shadcn-style primitives + Recharts.

## Run

```bash
npm install
npm run dev      # http://localhost:3001
npm run test     # vitest
```

`NEXT_PUBLIC_ADMIN_API_URL` points at the FastAPI backend. Leave it empty to
use same-origin `/api/admin`. Never put a bot token in a `NEXT_PUBLIC_` var.

## Screens (15)

| Route | Purpose | Permission |
| --- | --- | --- |
| `/` | Action queue first, then metrics and charts | `dashboard.view` |
| `/users`, `/users/[userId]` | Search, suspend, adjust wallet | `users.view` |
| `/orders`, `/orders/[orderId]` | Payment review queue, approve / reject / refund | `orders.view` |
| `/products` | Categories, products, plans, duration-ladder generator | `products.view` |
| `/panels` | X-UI / Marzban / Marzneshin / Hiddify health, test, sync | `panels.view` |
| `/servers` | Load, latency, capacity, visibility | `servers.view` |
| `/coupons` | Single and bulk codes, archive | `coupons.view` |
| `/campaigns` | Windows, flash sales, discount-given vs revenue | `campaigns.view` |
| `/analytics` | Revenue, orders, signups, churn, mixes, CSV export | `analytics.view` |
| `/broadcast` | Segmented sends, quiet hours, live delivery | `broadcast.view` |
| `/tickets`, `/tickets/[ticketId]` | Support queue, oldest first | `tickets.view` |
| `/wallet` | Ledger with running balance | `wallet.view` |
| `/logs` | Audit trail with before/after and correlation id | `logs.view` |
| `/settings` | The 13 pricing / cashback / referral policy keys | `settings.view` |
| `/permissions` | Operators and the full role matrix | `permissions.view` |

## Design rules that must hold

- **Green settled, amber waiting, red act now.** Nothing else is coloured.
  Expiry is amber, not red; it is a lifecycle, not a fault.
- **Queues before vanity metrics.** The dashboard opens with what needs a
  human, not with a revenue number nobody can act on.
- **Denser than the Mini App.** 36px buttons, 40px rows, `2xs` type. This is
  a tool used for eight hours, not a shop browsed for two minutes.
- **No gradient.** The customer brand is a blue\u2192purple gradient; the panel is
  flat slate so saturation can mean something.
- **Destructive actions**: confirm dialog + reason of at least 5 characters +
  a preview of the resulting state. The dialog stays open if the call fails.
- **Illegal-by-state controls are hidden, not disabled.**

## Tests

`tests/` covers the pure logic: the RBAC denial paths and `canAssignRole`,
the `waitTone` thresholds, Persian label completeness, chart formatting,
duration-ladder arithmetic (including the deliberate weekly premium), and
order action gating by state and role.

## Not built

The FastAPI `/api/admin/*` routes that `src/lib/api.ts` expects, the
`/sign-in` page, and the create dialogs behind the "new product / panel /
server / coupon / campaign" buttons. Nothing in this app has been installed,
type-checked, built or run: the authoring sandbox has no Node.
