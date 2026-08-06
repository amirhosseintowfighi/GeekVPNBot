# Geek VPN

Premium Telegram VPN sales platform. Persian-first, production-grade, modular.

> **Phase 3 - VPN Panel Abstraction Layer.** Subscriptions can now be
> fulfilled against five different VPN panels through one interface.
> Adding a sixth requires only a new adapter module - no edits to the
> registry, factory, port or business logic. Packages, payments, the
> wallet and the bot purchase flows arrive in Phase 4.

## What is in the box today

| Area | Status |
| --- | --- |
| Clean Architecture layout + enforced layering | done |
| FastAPI application factory, problem-details errors, correlation ids | done |
| Aiogram 3 webhook receiver with secret-token verification | done |
| PostgreSQL (async SQLAlchemy 2.0) engine, session factory, unit of work | done |
| Redis client + `Cache` port implementation | done |
| Alembic with advisory-locked, config-driven migrations | done |
| Docker multi-stage image, Compose stack, Nginx edge | done |
| Structured JSON logging with secret redaction | done |
| Typed settings with production guardrails | done |
| Dependency injection composition root | done |
| Liveness / readiness health checks | done |
| Ruff, mypy strict, import-linter, pytest, pre-commit, GitHub Actions | done |
| Telegram Mini App + Login Widget signature verification | done |
| JWT access tokens (HS256, pinned algorithm, required claims) | done |
| Opaque refresh tokens: rotation, reuse detection, Redis revocation list | done |
| Sessions with separate customer / admin lifetimes | done |
| RBAC: 5 roles, 28 permissions, per-admin grant & deny overrides | done |
| Admin login: Argon2id, lockout, TOTP 2FA, rate limits, IP allow-list | done |
| Append-only audit log enforced by PostgreSQL rules | done |
| User model, Admin model, runtime settings module | done |
| VPN panel abstraction, plugin registry, five adapters | Done |
| Packages, payments, wallet, bot purchase flows | **Phase 4+** |

## Quick start

```bash
cp .env.example .env          # then edit the secrets
make up                       # docker compose up -d, with hot reload
curl localhost:8000/health/ready
```

API docs (local only): <http://localhost:8000/api/v1/docs>

Without Docker:

```bash
python -m venv .venv && source .venv/bin/activate
make install                  # editable install + git hooks
make check                    # lint, types, architecture, tests
```

## Layout

```
src/geekvpn/
  domain/          pure Python. entities, value objects, events, errors
  application/     use cases and ports (Protocols). no frameworks
  infrastructure/  settings, logging, Postgres, Redis, DI, health probes
  presentation/    FastAPI routers, Aiogram handlers, schemas
  entrypoints/     one module per container command
migrations/        Alembic
tests/             unit / integration / architecture
docker/            Dockerfile and Nginx configuration
docs/              architecture, conventions, development, deployment, panels
docs/uml/          PlantUML diagrams for the panel layer
```

Dependencies point inward only: `presentation -> infrastructure -> application -> domain`.
This is verified by `lint-imports` and by `tests/architecture/`, so it cannot rot.

## Documentation

- [docs/architecture.md](docs/architecture.md) - layers, wiring, request lifecycle
- [docs/conventions.md](docs/conventions.md) - naming, typing, errors, commits
- [docs/development.md](docs/development.md) - local setup, testing, migrations
- [docs/deployment.md](docs/deployment.md) - Docker, Nginx, operations
- [docs/authentication.md](docs/authentication.md) - Telegram auth, JWT, refresh rotation, threat model
- [docs/rbac.md](docs/rbac.md) - roles, permissions, enforcement
- [docs/settings-and-audit.md](docs/settings-and-audit.md) - runtime settings and the audit trail
- [docs/panels.md](docs/panels.md) - VPN panel abstraction, capability matrix, adding a panel
- [docs/uml/](docs/uml/) - PlantUML class, sequence and state diagrams

## Commands

`make help` lists everything. The important ones:

| Command | Purpose |
| --- | --- |
| `make up` / `make down` | run or stop the stack |
| `make check` | exactly what CI runs |
| `make fmt` | format and autofix |
| `make revision m="..."` | autogenerate a migration |
| `make migrate` | apply migrations |

## Creating the first administrator

After the first migration, there are no admins - by design, since a default
account with a default password is the most common way a panel gets taken over.

```bash
docker compose exec api python -m geekvpn.entrypoints.create_admin \
  --username amir --role super_admin
```

The password is read from `GEEKVPN_ADMIN_PASSWORD` or prompted interactively; it
is never taken from the command line, where it would land in shell history. The
command refuses to overwrite an existing account.

A `super_admin` must enrol TOTP before the account can be used - mandatory 2FA
that silently degrades to password-only is not 2FA.
