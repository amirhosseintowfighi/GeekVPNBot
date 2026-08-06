# Settings and audit

## Two kinds of configuration

**Boot configuration** - `.env`, read by pydantic-settings, immutable at
runtime: database URLs, secrets, ports, the bot token. Changing one is a
deployment. Nothing at runtime can rewrite it, which is precisely the point:
an admin panel that can change the database password is an admin panel that can
exfiltrate the database.

**Runtime settings** - `platform_settings` in Postgres, editable by admins with
`settings.write`: maintenance mode, support handle, whether registration is
open. These are business switches, not infrastructure.

If you are unsure which a value is, ask whether a support agent should be able
to change it at 2am without a deploy.

## Declared registry

Every runtime setting is declared in code with a key, type, default and
description. Writing an undeclared key is a 404, and writing a wrongly typed
value is a 422 - so the table cannot silently fill with typos that nothing
reads. A corrupt stored value falls back to the declared default rather than
crashing the request: a settings problem must never take the platform down.

Current keys: `platform.maintenance_mode`, `platform.maintenance_message`,
`identity.registration_enabled`, `security.admin_session_ip_pinning`,
`support.telegram_handle`, `support.hours`.

Values are cached in Redis for 5 minutes and invalidated on write.

## Audit log

An append-only record of who did what, to what, from where, and whether it
worked.

Every entry carries: action, outcome, timestamp, actor type/id/label, target
type/id, IP, user agent, correlation id, and a JSONB metadata blob.

The correlation id is the same `X-Request-ID` that appears in the structured
logs, so an audit entry links directly to the full request trace.

### Append-only, enforced by Postgres

```sql
CREATE RULE audit_logs_no_update AS ON UPDATE TO audit_logs DO INSTEAD NOTHING;
CREATE RULE audit_logs_no_delete AS ON DELETE TO audit_logs DO INSTEAD NOTHING;
```

Rules rewrite the query itself, so an `UPDATE` becomes literally nothing. There
is no application code path - including one running as a compromised
application user - that can rewrite history. Only the table owner, used by
migrations, can drop the rules. Chosen over a trigger because a rule cannot be
disabled per-session, and over application-level discipline because application
level discipline is not a control.

### Redaction

`password`, `token`, `secret`, `init_data`, `authorization` and `totp_code` are
rejected from metadata at the recorder. An audit log that leaks credentials is
worse than no audit log, because it concentrates them.

### What is audited today

Login success/failure, logout, logout-all, token refresh, token reuse,
account lockout, TOTP enable/disable/failure, permission denial, IP rejection,
user registration/suspension/reinstatement, admin create/update/role change/
permission change/password change/disable, session revocation, setting change.

### Retention

Rows are never updated or deleted by the application. Partitioning by month is
the intended path once volume justifies it; the `occurred_at` index is already
in place.
