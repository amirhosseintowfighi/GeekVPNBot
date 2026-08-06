# Developer guide

## Requirements

Python 3.12+, Docker with Compose v2, `make`.

## Setup

```bash
git clone <repo> && cd geekvpn
cp .env.example .env
python -m venv .venv && source .venv/bin/activate
make install         # editable install with dev extras + pre-commit hooks
```

`make install` installs the git hooks. Do not skip it: the hooks are the same
checks CI runs.

## Running

```bash
make up        # full stack with hot reload (dev overlay)
make logs      # follow logs
make ps        # container status
make down      # stop
make reset     # stop AND delete volumes (destroys local data)
```

Ports in development: API `8000`, bot `8081`, Nginx `80`, Postgres `5432`,
Redis `6379`. In production only Nginx is published.

## Verifying it works

```bash
curl -s localhost:8000/health/live  | jq
curl -s localhost:8000/health/ready | jq
curl -s localhost:8000/api/v1/info  | jq
curl -s localhost/nginx-health
```

`/health/ready` returns `503` with a per-dependency breakdown when Postgres or
Redis is unreachable - stop the `postgres` container and try it, the response
tells you exactly which dependency failed and why.

## Quality gates

```bash
make fmt     # ruff format + autofix
make lint    # ruff check, no fixes
make type    # mypy --strict
make arch    # import-linter layering contracts
make test    # pytest
make check   # all of the above, identical to CI
```

## Tests

```bash
pytest                      # everything
pytest -m unit              # fast, no I/O
pytest -m integration       # ASGI app + dependencies
pytest -m architecture      # layering
make cov                    # coverage report
```

Unit tests must not open a socket. If a test needs Postgres or Redis, it belongs
in `tests/integration` and must be marked.

## Migrations

```bash
make revision m="create users table"
# review the generated file by hand - autogenerate is a draft, not an author
make migrate
alembic downgrade -1        # verify the downgrade works before committing
```

The URL comes from `Settings`, so `alembic.ini` holds no credentials. Migrations
take a Postgres advisory lock, so concurrent replicas cannot race.

## Telegram locally

The bot only receives webhooks. To test against real Telegram, expose port 8081
with a tunnel and set:

```
TELEGRAM__WEBHOOK_BASE_URL=https://<your-tunnel>
TELEGRAM__SET_WEBHOOK_ON_STARTUP=true
```

Then send `/ping` to the bot; it replies `pong`. That is the only handler in
Phase 1 and it exists purely to prove the wiring.

## Adding a new module (from Phase 2 on)

1. Domain types in `domain/<context>/`, with no imports from other layers.
2. Ports in `application/ports/`, use cases in `application/<context>/`.
3. Adapters in `infrastructure/`, wired in `di/container.py`.
4. Routers/handlers in `presentation/`.
5. Migration, tests at all three levels, docs.
6. `make check` must be green before the module is considered done.
