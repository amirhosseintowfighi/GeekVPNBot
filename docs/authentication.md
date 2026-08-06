# Authentication

Geek VPN has two populations with very different risk profiles, so it has two
authentication paths that share one session engine.

| | Customer | Admin |
|---|---|---|
| Credential | Telegram signature | username + password (+ TOTP) |
| Access token TTL | 15 min | 15 min |
| Refresh TTL (sliding) | 30 days | 12 hours |
| Absolute session cap | 180 days | 24 hours |
| Second factor | n/a | required for `super_admin` |
| IP allow-list | no | optional (`AUTH__ADMIN_IP_ALLOWLIST`) |

A customer who has to log in again is a lost sale. An admin session that lives
for a month is a breach waiting to happen. Same machinery, different policy
object - see `SessionPolicy`.

## Telegram authentication

We never ask a customer for a password. Telegram already proved who they are;
we verify Telegram's proof.

### Mini App (`initData`)

1. Drop `hash` and `signature` from the payload.
2. Sort remaining fields by key, join as `key=value` with `\n`.
3. `secret = HMAC_SHA256(key="WebAppData", msg=bot_token)`
4. Compare `HMAC_SHA256(key=secret, msg=check_string)` against `hash` with
   `hmac.compare_digest`.
5. Reject if `auth_date` is older than `TELEGRAM__AUTH_MAX_AGE_SECONDS`
   (default 24h) or more than 60s in the future.

### Login Widget

Identical, except `secret = SHA256(bot_token)`.

The two derivations are **not** interchangeable, and using the widget secret to
validate Mini App data is a well-known real-world vulnerability. There is a
regression test that specifically asserts one cannot validate the other.

### Why the freshness window matters

`initData` is a bearer credential. Without an expiry, a single copy leaked from
a browser history, a proxy log, or a screenshot is a permanent login. 24 hours
is Telegram's own recommendation and matches how long a Mini App session is
realistically kept open.

## Access tokens (JWT)

- `HS256`. There is exactly one issuer and one verifier, both ours. RS256 buys
  key separation we do not need yet and costs key management we would do badly.
  The moment a third party must verify our tokens, switch to RS256 - the
  interface (`AccessTokenService`) does not change.
- Secret must be at least 32 characters; the service refuses to construct
  otherwise, so a weak key fails at boot rather than at breach.
- Claims: `iss aud sub sid typ styp jti iat nbf exp role perms`.
- Verification requires `exp iat sub iss aud` to be present, pins the algorithm
  list to `["HS256"]` (blocks the `alg: none` attack), allows 10s of leeway,
  and rejects any `typ` other than `access`.
- `perms` is embedded so the hot path needs no database read. The price is up to
  15 minutes of staleness after a permission change, bounded by the short TTL
  and by the revocation list below.

## Refresh tokens

- Opaque, 32 random bytes, base64url. Not a JWT - there is nothing to read
  inside, and it is single-use.
- Only `SHA-256(token)` is stored. A database dump does not yield usable
  tokens. (Argon2 is unnecessary here: the token is 256 bits of entropy, not a
  human password, so there is nothing to brute-force.)
- **Rotation**: every refresh spends the old token and issues a new one.
- **Reuse detection**: presenting an already-spent token revokes the entire
  session, every refresh token in its chain, and pushes the session onto the
  Redis revocation list. Both the victim and the thief are logged out - we
  cannot tell them apart, so nobody keeps access. The event is audited as
  `auth.token.reuse_detected`.

The claim is a conditional `UPDATE ... WHERE used_at IS NULL` returning
`rowcount`, not a read-then-write. Two concurrent refreshes therefore produce
exactly one winner; the loser is treated as reuse.

## Revocation

A logout must take effect immediately, but access tokens are stateless. Redis
holds a short-lived deny list:

- `geekvpn:revoked:session:<sid>` - one session killed.
- `geekvpn:revoked:subject:<id>` - an epoch; every token issued before it is
  dead (used by "log out everywhere", suspension, password change).

Entries live for `access_ttl + 60s` only, because after that the token has
expired anyway. The list **fails open**: if Redis is down, tokens verify
normally. This is a deliberate availability trade-off - the alternative is that
a Redis blip logs out every customer at once. The exposure window is capped at
15 minutes, and the underlying refresh token is already dead in Postgres.

## Admin login

Order of checks, and why:

1. **Rate limit** (per username *and* per IP, 10 per 5 minutes) - before any
   expensive work, so Argon2 cannot be used as a DoS amplifier.
2. **IP allow-list**, if configured.
3. **Lookup + password verify.** An unknown username still runs a verification
   against a dummy hash so response timing does not reveal which usernames
   exist.
4. **Lockout**: 5 failures locks the account for 15 minutes; the correct
   password is refused while locked.
5. **TOTP**, mandatory for `super_admin`. A super admin with no enrolled secret
   cannot log in at all - mandatory 2FA that silently degrades is not 2FA.
6. Used TOTP codes are held in Redis for 90 seconds so an intercepted code
   cannot be replayed inside its own validity window.

Every branch above writes an audit entry.

## Endpoints

| Method | Path | Auth |
|---|---|---|
| POST | `/api/v1/auth/telegram/mini-app` | public |
| POST | `/api/v1/auth/telegram/widget` | public |
| POST | `/api/v1/auth/refresh` | refresh token |
| POST | `/api/v1/auth/logout` | bearer |
| POST | `/api/v1/auth/logout-all` | bearer |
| GET | `/api/v1/auth/me` | bearer (customer) |
| GET | `/api/v1/auth/sessions` | bearer (customer) |
| POST | `/api/v1/admin/auth/login` | public |
| GET | `/api/v1/admin/auth/me` | bearer (admin) |

All failures return `application/problem+json` with a stable machine-readable
`code`; 401s carry `WWW-Authenticate: Bearer`.

## Bot authentication

Updates arriving over the webhook are already authenticated by Telegram (the
secret-token header, verified in Phase 1). `IdentityMiddleware` resolves or
registers the user and injects it into every handler, so bot handlers never
touch authentication logic. `/start ref_XXXX` is parsed there too.

## Threat model

| Threat | Control |
|---|---|
| Forged `initData` | HMAC verify, constant-time compare |
| Replayed `initData` | 24h freshness window |
| `alg: none` / key confusion | algorithm pinned, required claims |
| Stolen refresh token | rotation + reuse detection + session kill |
| Stolen access token | 15 min TTL + Redis revocation list |
| Admin password spray | per-user and per-IP rate limit, lockout |
| Username enumeration | dummy-hash verification, identical errors |
| TOTP interception | 90s replay guard, 1-step window |
| Compromised admin account | short absolute cap, IP allow-list, deny rules |
| Insider tampering with history | append-only audit table (DB rules) |
