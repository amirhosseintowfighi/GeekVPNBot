# Changelog

All notable changes to Geek VPN are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-08-03 - Phase 11: Analytics

### Added

- **Analytics domain** (`domain/analytics/`, 15 modules, 85 exports): pure
  arithmetic with no repository, clock or I/O, so the admin screen, the CSV
  export and any future digest cannot disagree about what "net revenue" means.
  - `enums.py`: `MetricKey` (20 metrics, each carrying its own unit and its own
    direction of virtue via `lower_is_better()`), `MetricFormat`, `Granularity`,
    `FunnelStage`, `SegmentKind`, `BadgeKind`, `TrendDirection`.
  - `calendar.py`: Jalali conversion and Persian labels, verified against
    `2026-03-21 -> 1405/1/1`, `2026-08-03 -> 1405/5/12`, `2026-03-20 -> 1404/12/29`.
  - `timeframe.py`: half-open `DateRange` so adjacent periods tile exactly and
    `previous()` cannot double-count the boundary day. **Weeks start Saturday.**
  - `series.py`: `TimeSeries` zero-fills every bucket, because a chart that
    omits empty days draws a smooth line through an outage. `Breakdown` folds
    the tail past the top 6 into سایر.
  - `metrics.py`: `MetricCard` computes its own arrow. `percent_change()`
    returns `None` against a zero baseline -- first data point, not infinite
    growth -- and movement under 1% reports as flat.
  - `revenue.py`, `funnel.py`, `retention.py`, `referral.py`, `nodes.py`,
    `segmentation.py`, `gamification.py`, `dashboard.py`.
- **Analytics application layer** (`application/analytics/`, 8 modules, 34
  exports): `AnalyticsService` (bundle assembly, previous period fetched on
  every call), `DashboardService` (an action queue, not a report),
  `SegmentationService` (rules evaluated fresh; also a natural
  `AudienceResolver` for the Phase 10 broadcast engine), `MarketingService`
  (advice, never auto-fired campaigns), `GamificationService`, and a CSV
  exporter that emits a UTF-8 BOM for Excel on Windows.
- **Documentation**: `docs/analytics.md` with every metric formula, the funnel
  and cohort semantics, segmentation rules, gamification rules and Jalali
  bucketing; the `AnalyticsBundle` contract and export endpoint added to
  `admin/docs/api-contract.md`.

### Decisions

- Money is a plain `int` of Toman inside analytics. The `Money` value object is
  not used: analytics sums thousands of rows per request, and the payments
  context already enforced the invariants it exists to protect.
- Churn has a 14-day grace period. Somebody who expired yesterday has not
  churned; they have not renewed yet.
- LTV falls back to `ARPU x lifetime_months` when churn is zero rather than
  reporting infinite customer value.
- Unlimited plans are counted separately from metered GiB, never assigned a
  notional cap.
- Offline nodes contribute zero fleet capacity.
- Gamification points are recomputed from a snapshot on every read and buy
  nothing. A spendable badge is money, and money belongs in payments with an
  audit trail.
- `Funnel.build()` forces monotonically non-increasing counts; a funnel that
  grows downstream is a data bug, not a chart.

### Not included

- No infrastructure adapters: the readers in `application/analytics/ports.py`
  are unimplemented `Protocol`s awaiting SQL aggregates.
- No HTTP routes for `/api/admin/analytics` or the CSV export.
- No caching; `ReportCache` is declared and unused.
- Phase 11 shipped documentation instead of tests, as requested.

## [0.3.0] - 2026-08-02 - Phase 3: VPN Panel Abstraction Layer

### Added

- **Domain vocabulary for panels** (`domain/panels/`): `PanelKind`,
  `Capability`, `AccountState`, `Protocol`, `SubscriptionFormat`, plus value
  objects `AccountSpec`, `PanelAccount`, `AccountUsage`, `TrafficQuota`,
  `PanelAccountRef`, `NodeInfo`, `PanelHealth`, `SubscriptionPayload`.
  `AccountState.is_usable` is true only for `ACTIVE`, so an unrecognised panel
  status withholds access rather than silently granting it.
- **Panel error taxonomy** (`domain/panels/errors.py`): `PanelError` carrying a
  `retryable` flag, with `PanelUnreachable`, `PanelRateLimited`,
  `PanelAuthFailed`, `AccountNotFound`, `AccountAlreadyExists`, `QuotaExceeded`,
  `CapabilityNotSupported` and `PanelContractViolation`.
- **Base Panel Interface** (`application/ports/panel.py`): a `Protocol` defining
  nine mandatory operations and four capability-gated ones. Every mutating
  method takes a keyword-only `idempotency_key`.
- **Plugin architecture** (`infrastructure/panels/`): `PanelRegistry`, the
  `@register_panel` decorator, `load_bundled_adapters()` package-walk discovery
  that skips underscore-prefixed helper modules, and a `PanelFactory` that
  contains no panel-specific logic whatsoever.
- **Shared HTTP client** (`infrastructure/panels/http.py`): full-jitter
  exponential backoff, retries limited to timeouts and 5xx, terminal handling of
  4xx, `Retry-After` parsing, and body truncation for logs.
- **Five adapters**: PasarGuard (8 capabilities), Marzban (6), Marzneshin (6),
  Sanaei/3x-ui (4) and Alireza/x-ui (4). The two x-ui forks share an abstract
  base and differ only in two class attributes.
- **Documentation**: `docs/panels.md` with the capability matrix, the adapter
  contract, per-panel gotchas and a worked example of adding a new panel; three
  PlantUML diagrams in `docs/uml/` (class, provisioning sequence, account state).
- **Tests**: eight modules including a conformance suite parametrised over the
  registry, so a newly registered panel is covered automatically, and an
  extensibility test that registers a fictional panel to prove no shipped code
  needs editing.

### Notes

- Request and response shapes for Marzneshin, 3x-ui and x-ui were derived from
  READMEs, wikis, SDKs and Postman collections rather than a live OpenAPI
  document. Verify against a real instance before enabling those panels in
  production.

## [0.2.1] - 2026-08-02 - Phase 2 Principal Engineer review

### Fixed

- **Critical:** refresh-token rotation minted a replacement whose `jti` did not
  match the persisted token id, so rotated tokens could not be revoked.
  `_mint()` now accepts an explicit `token_id`.
- **High (security):** admin login leaked a username-enumeration timing oracle
  by skipping password verification for unknown usernames. A dummy Argon2 hash
  is now verified on the miss path.
- **Medium:** untyped `now` parameter in `authenticate_telegram._create`.
- **Medium:** function-local imports in `manage_admins.py` hoisted to module
  level, restoring Clean Architecture import discipline.
- **Medium:** `subject_type` threaded through the session port, repository,
  fakes and both call sites, so user and admin ids can no longer collide when
  revoking sessions.

### Added

- `tests/unit/test_review_regressions.py` pinning each fix.
- This changelog.

## [0.2.0] - 2026-08-02 - Phase 2: Authentication & Infrastructure

### Added

- Telegram authentication for Mini App `initData` and Login Widget payloads,
  with constant-time HMAC verification and replay protection.
- JWT access tokens and rotating refresh tokens with reuse detection, session
  tracking, and absolute plus sliding TTLs.
- RBAC: 28 granular permissions, five admin roles, and per-admin grant/deny
  overrides where deny always wins.
- Admin authentication with Argon2id hashing, TOTP two-factor, account lockout,
  IP allowlisting and rate limiting.
- Append-only audit log with database-level rules blocking updates and deletes.
- Platform settings module with Redis caching.
- Identity and audit migration, sixteen API endpoints, and RFC 7807 error
  responses throughout.

## [0.1.0] - 2026-08-02 - Phase 1: Project Foundation

### Added

- Clean Architecture skeleton with domain, application, infrastructure and
  presentation layers, enforced by import-linter contracts.
- FastAPI application factory, Aiogram 3 webhook bot, SQLAlchemy 2 with async
  PostgreSQL, Redis, Alembic with advisory-lock migrations.
- Docker Compose stack, Nginx reverse proxy, structured JSON logging with
  correlation ids, liveness and readiness probes.
- Tooling: ruff, mypy strict, pytest, pre-commit, GitHub Actions CI.
