# Security report — Phase 13

This is a report, not a brochure. Where a control is only partly implemented, or
implemented but never executed in this environment, it says so. The
**verification status** table near the end is the part to read first if you only
read one section, because it is the part most security documents get wrong by
omission.

---

## 1. What we are actually protecting

Three things, in order of how much damage their loss causes:

1. **Money in motion.** Card-to-card transfers approved by hand, crypto transfers,
   and wallet balances. The realistic attack is not a cryptographic break; it is
   a duplicate receipt approved twice, or a refund larger than the capture.
2. **Customer identity data.** Telegram ids, card numbers on receipts,
   transaction references. In this market that data being leaked is a concrete
   harm to the customer, not a compliance footnote.
3. **Panel credentials.** One set of panel credentials is every customer's
   service. This is the highest-value secret in the system and it is the reason
   encryption at rest exists here at all.

### Threat actors we designed against

| Actor | Realistic capability | Primary controls |
|---|---|---|
| Opportunistic scripted abuse | Automated signup, credential stuffing, receipt spam | Rate limiting per policy, captcha after 3 failures, lockout after 8 |
| A customer acting in bad faith | Forged receipts, duplicate references, refund abuse | Receipt digest uniqueness, `uq_wallet_user_kind_reference`, `billing_payments_refund_within_capture`, manual review |
| A compromised operator account | Full admin API access with that role's permissions | RBAC with 29 permissions, deny-beats-grant resolution, 2FA with TOTP + recovery codes, admin IP allowlist, audit log of every action |
| Network attacker | Interception, forged forwarding headers | TLS with HSTS when deployed, `X-Forwarded-For` counted from the right with an explicit trusted-hop count |
| Database exfiltration | Read access to Postgres | AES-256-GCM for panel credentials and card data, blind index for lookups, argon2 for admin passwords, scrypt for recovery codes |

### Explicitly out of scope

- A compromised host running the API. Anything with the process memory has the
  master key; encryption at rest does not defend against that and claiming it
  does would be dishonest.
- Telegram itself. If the bot token leaks, the bot is the attacker's. Rotation is
  the answer, not a control in this codebase.
- Denial of service at the network layer. That is the reverse proxy's job.

---

## 2. Control matrix

| Requirement | Where it lives | Notes |
|---|---|---|
| Rate limiting | `infrastructure/security/throttling.py`, `sliding_window.py`, `presentation/api/security_middleware.py` | 20 named policies. Sliding window in Redis via one Lua script, so the check is atomic |
| Encryption | `infrastructure/security/crypto.py` | AES-256-GCM, HKDF-derived keys, key ids in the token, blind index for equality lookups |
| Secrets | `infrastructure/security/secrets_provider.py` | `NAME_FILE` beats `NAME`; weak-value detection; no `get_or_default` |
| 2FA | `infrastructure/security/totp.py`, `recovery_codes.py` | RFC 6238 TOTP; ten single-use scrypt-hashed recovery codes |
| Captcha | `infrastructure/security/captcha.py`, `captcha_store.py` | Persian-word arithmetic; accepts Persian and Arabic-Indic digits |
| IP whitelist | `infrastructure/security/ip_allowlist.py` | CIDR, IPv6, and correct client-address resolution |
| XSS | `infrastructure/security/escaping.py`, CSP in `security_middleware.py` | Escaping for Telegram HTML; URL scheme allowlist; `default-src 'none'` |
| CSRF | `infrastructure/security/csrf.py` | Signed double-submit, scoped to the cookie paths only |
| SQL injection | `scripts/sqli_gate.py` | AST gate in CI; repository is clean |
| Caching | `infrastructure/cache/keys.py`, `report_cache.py` | Jittered TTL, single-flight lock, `SCAN` never `KEYS` |
| Redis optimisation | `report_cache.py` | `MGET` batching, non-transactional pipelining for warm-up |
| Database optimisation | `migrations/versions/0004_*` | 22 indexes, most partial; trigram index for ticket search |
| Stress testing | `scripts/loadtest/harness.py`, `k6.js` | Stdlib harness plus a k6 script for a real rig |

---

## 3. The decisions worth arguing with

### Rate limiting keys on the subject, not the IP

Iranian mobile carriers place tens of thousands of subscribers behind a single
NAT address. An IP-keyed login limit is therefore a denial of service against a
whole carrier: one person guessing passwords locks out everybody on Irancell.
Authenticated traffic keys on the subject; only anonymous traffic falls back to
the address, and `auth.admin_login` is IP-keyed on purpose because there the
username is attacker-supplied.

### Only failures count

`auth.login`, `auth.admin_login`, `auth.totp` and `auth.recovery_code` are
`failures_only`. A customer who signs in correctly forty times has done nothing
wrong, and limiting them produces support tickets instead of security.

### The limiter fails open; the lockout does not

If Redis is unavailable, rate limiting stops and requests proceed. This is a
deliberate availability choice, and it is defensible **only** because the strong
control — consecutive-failure lockout — is counted in Postgres, not Redis. A
Redis outage costs us throttling, not authentication. The captcha store, by
contrast, fails **closed** on write: losing a challenge would weaken a control.

### CSRF is scoped honestly

The admin panel and Mini App authenticate with `Authorization: Bearer`. A
cross-site page cannot set that header, so those endpoints are not vulnerable to
CSRF, and tokens there would be ceremony that a review mistakes for a control.
The genuinely exposed surface is the refresh cookie, so that is where the
double-submit token is enforced, alongside `HttpOnly`, `SameSite=Lax` and
`Secure` when deployed.

### The forged forwarding header

The most common real vulnerability in IP allowlisting is reading the leftmost
`X-Forwarded-For` entry, which the client controls. `client_ip()` counts from the
**right** by an explicit trusted-hop count, and ignores the header entirely when
that count is zero. This is demonstrated as a test, not asserted as a comment:
`test_a_spoofed_leftmost_entry_cannot_impersonate_an_allowed_address` asserts
both that the correct reading refuses the request and that the naive reading
would have admitted it.

### Admin IP refusals answer 404, not 403

Confirming to an unapproved network that an admin API exists at a path is free
reconnaissance.

### Encryption uses a separate master key

`SECURITY__ENCRYPTION_MASTER_KEY` is distinct from `SECURITY__SECRET_KEY` and the
production guardrail refuses to boot if they are equal. Sharing one secret means
the JWT key can never be rotated without re-encrypting every stored card number,
so the two rotations would be permanently coupled.

### Decryption gives no oracle

Wrong key, wrong context and tampered ciphertext all raise the identical error
with the identical message. Distinguishing them is a decryption oracle.

### The captcha answer is stored in plain text

On purpose. The answer is a number under fifty; hashing it is theatre, since an
attacker can enumerate the whole space instantly. The protection comes from the
three-attempt limit and the three-minute expiry, and the strength claim is
limited accordingly: this stops naive scripted abuse. It does not stop a
determined attacker with an OCR pipeline, and it is not claimed to.

### Recovery codes check every hash even after a match

Returning early on the first match leaks, through timing, which code matched.

### `pg_trgm` rather than a like-for-like index

`SyncTicketRepository.search` uses `ILIKE '%term%'`. A leading wildcard cannot
use a B-tree in any form, so that endpoint was a guaranteed full scan of every
support message. The extension is created in the migration rather than assumed.

### Indexes are not built concurrently

`migrations/env.py` takes an advisory lock and runs the whole migration in one
transaction, and `CREATE INDEX CONCURRENTLY` cannot run inside a transaction.
Building concurrently would mean either dropping that lock — allowing two
deployments to migrate simultaneously — or leaving invalid indexes behind on
failure. At current table sizes a plain build takes seconds. If these tables
reach tens of millions of rows the right answer is a separate maintenance
script, not a weaker lock.

### Authorisation data is never cached

`should_cache()` refuses any key prefixed `auth.`, `permissions.` or `session.`.
A cached permission check keeps working after access is revoked.

---

## 4. Verification status — read this section

The sandbox this was built in has no `redis`, `sqlalchemy`, `alembic`, `fastapi`,
`starlette`, `argon2` or `aiogram`, and no real `pytest` (a custom shim and
runner stand in). That constrains what can honestly be claimed.

| Component | Status |
|---|---|
| `crypto.py` | **Executed.** Round-trip, rotation, blind index, card masking, tamper detection all run |
| `secrets_provider.py` | **Executed.** File convention, weakness detection, redaction |
| `throttling.py` | **Executed.** 20 policies, keying, lockout ladder, header emission |
| `captcha.py` | **Executed.** Generation, Persian digit folding, expiry-before-correctness |
| `recovery_codes.py` | **Executed.** Hashing, typing tolerance, single use, timing-safe comparison |
| `ip_allowlist.py` | **Executed.** CIDR matching and the forged-header bypass |
| `escaping.py` | **Executed.** HTML escaping, URL scheme refusal, bidi stripping |
| `csrf.py` | **Executed.** Signing, session binding, double-submit, cookie attributes |
| `cache/keys.py` | **Executed.** Key identity, jitter, TTL policy |
| `persistence/types.py` | **Parsed and gated only** (needs SQLAlchemy), but the digest length and context separation it depends on were executed — and caught a real defect, below |
| `sliding_window.py` | **Parsed and gated only.** Needs Redis. The Lua script has never run |
| `captcha_store.py` | **Parsed and gated only.** Needs Redis |
| `report_cache.py` | **Parsed and gated only.** Needs Redis. The single-flight lock is unproven |
| `security_middleware.py` | **Parsed only.** Needs Starlette. No header has ever been emitted by a running server |
| `migration 0004` | **Parsed and chain-gated only.** No index has ever been created |
| Load harness | **Report maths executed.** No load has ever been generated against a running API |
| SQLi gate | **Executed, and proven against four real injections** |

**What this means in practice.** The parts that encode judgement — which policy
applies, how a key is derived, what counts as a safe URL, when a lockout starts —
are tested and run. The parts that are plumbing to infrastructure we do not have
are structurally verified and no more. Before deployment, the load harness's rate
limit scenario must be run against a real instance; a run reporting zero 429s
means the limiter is not working, and that failure is invisible to every test in
this repository.

---

## 5. Known gaps and debt

1. **`argon2-cffi` is not installed here**, so `Argon2Hasher` has never been
   executed in this environment either. It is a dependency, not new code.
2. **The encryption mechanism is complete; the application of it is not.**
   `0004` adds `proof_encrypted`, `card_encrypted` and `card_blind_index`, and
   `infrastructure/persistence/types.py` provides `EncryptedString`,
   `EncryptedCard`, `BlindIndex` and `CardBlindIndex` column types plus
   `card_blind_index_of()` for building query filters. What is still missing is
   the last two steps: the models must switch those columns over to the new
   types, and a backfill command must encrypt existing rows. Until both land,
   encryption at rest is *available* rather than *applied*, and
   `install_keyring()` must be called during start-up or the first read of an
   encrypted column raises `EncryptionNotConfiguredError` — deliberately loud,
   because the quiet alternative is storing plaintext in a column named
   `_encrypted`.
   The result-value path tolerates plaintext during the backfill window, which is
   a knowing trade: refusing would take the application down for every row not
   yet migrated, so the column can hold either form until the backfill finishes.
3. **Recovery codes are not yet enrolled anywhere.** The module is complete and
   tested; `admin_auth.py` still only checks TOTP.
4. **TOTP same-window replay protection remains the caller's responsibility** and
   is implemented in `admin_auth.py`, not centrally.
5. **40 pre-existing test failures** elsewhere in the suite, surfaced when the
   test harness was repaired. They are unrelated to Phase 13 and are real debt:
   a missing cashback ceiling in the catalog domain, three missing methods
   (`PromotionScope.matches_target`, `TimeWindow.is_unbounded`,
   `Campaign.seconds_remaining`), a changed `HttpPanelAdapter` signature, and
   several tests needing SQLAlchemy.
6. **No dependency scanning or SAST in CI.** `pip-audit` and a `bandit` or `ruff`
   security ruleset would be cheap additions and are not present.
7. **No secret scanning in pre-commit.** The secrets provider makes leaks
   avoidable; it does not detect one already committed.

---

## 5a. A defect this work actually found

Worth recording because it is the kind of bug that a review does not catch and a
type checker cannot see. `types.py` originally defined the blind-index length as
the literal `64`, on the reasonable-sounding assumption that a SHA-256-based
digest is 64 hex characters. It is not: `crypto.py` truncates the blind index to
16 bytes, so the real digest is 32 characters. Two consequences followed:

1. The “this value is already a digest, do not digest it again” guard compared
   against 64 and therefore never fired. A caller passing a pre-computed index
   into a query would have had it hashed a second time and matched nothing — an
   empty result set, not an error, which is the worst possible failure mode for a
   duplicate-card check.
2. The constant was duplicated knowledge about another module.

The fix derives the length from `BLIND_INDEX_BYTES * 2` and separates it from the
declared column width, which stays at 64 so that lengthening the digest later is
a constant change rather than a table rewrite on a live payments table. It was
found by asserting the real length of a real digest against the constant, which
is the only reason it was found at all.

---

## 6. Operational checklist before going live

- [ ] `SECURITY__SECRET_KEY` and `SECURITY__ENCRYPTION_MASTER_KEY` set, distinct,
      at least 32 characters, delivered as `*_FILE` secrets rather than env vars
- [ ] `SECURITY__TRUSTED_PROXY_COUNT` set to the real number of proxies — a wrong
      value here silently breaks both the IP allowlist and per-IP rate limiting
- [ ] `SECURITY__CORS_ORIGINS` set to exact origins, never `*`
- [ ] `AUTH__ADMIN_IP_ALLOWLIST` populated, then verified from a disallowed
      address (expect a 404)
- [ ] `AUTH__BOOTSTRAP_ADMIN_PASSWORD` removed after first boot; the guardrail
      enforces this
- [ ] Run `python scripts/sqli_gate.py src migrations` in CI
- [ ] Run `python scripts/loadtest/harness.py --scenario ratelimit` and confirm
      429s appear
- [ ] Stop Redis and confirm the API still serves requests (fail-open posture)
- [ ] Confirm `Strict-Transport-Security` appears only on the deployed origin
- [ ] Call `install_keyring(lambda: container.keyring)` during start-up, then read
      one encrypted row to prove the keyring is reachable
