# Roles and permissions

## Model

A permission is a `resource.action` string, e.g. `orders.refund`. There are 28,
declared once in `domain/identity/permissions.py` as a `StrEnum`, so a typo is
an `AttributeError` at import time rather than a silent authorization hole.

Effective permissions are computed as:

```
effective = (role_defaults | explicitly_granted) - explicitly_denied
```

**Deny always wins**, including over `super_admin`. That is the emergency lever:
when an account is suspected of compromise at 3am, you add a deny rule and it
takes effect on the next token refresh - at most 15 minutes - without touching
roles or restarting anything.

## Roles

| Role | Intent |
|---|---|
| `super_admin` | Owner. Everything. Mandatory 2FA. |
| `admin` | Day-to-day operations. **Cannot** create admins or change settings. |
| `finance` | Payments, refunds, wallet adjustments, revenue metrics. |
| `support` | Tickets, read-only user data. **No** money permissions. |
| `viewer` | Read-only everywhere. Safe for analysts and new hires. |

The separation between `admin` and `super_admin` is the important one: an
operations account that can mint new super admins is not a privilege boundary,
it is a formality.

## Permission catalogue

`users.{read,write,suspend,impersonate}` · `admins.{read,write}` ·
`packages.{read,write}` · `orders.{read,refund}` · `payments.{read,approve}` ·
`wallet.{read,adjust}` · `panels.{read,write}` · `subscriptions.{read,write}` ·
`tickets.{read,reply,assign}` · `broadcast.send` · `campaigns.write` ·
`audit.read` · `settings.{read,write}` · `metrics.read`

## Enforcement

At the edge, declaratively:

```python
@router.post("/admins", dependencies=[Depends(requires(Permission.ADMINS_WRITE))])
async def create_admin(...): ...
```

The dependency reads `perms` from the verified token - never from the `role`
claim. A token that says `role: super_admin` with an empty `perms` list is
refused, which is asserted by a test.

Inside the domain, `Admin.require_permission()` raises `MissingPermissionError`.
Both layers enforce; the API layer gives a clean 403 without work, the domain
layer is the backstop for anything reached by another route (bot, worker, CLI).

Every denial is audited as `auth.permission.denied` with the actor, the missing
permission and the target - so "who tried to refund that order" is answerable.

## Adding a permission

1. Add the member to `Permission`.
2. Add it to the relevant `ROLE_PERMISSIONS` entries.
3. Attach `requires(...)` to the route.

No migration. Permissions are values in JSONB, not rows.
