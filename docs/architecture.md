# Architecture

## The one rule

Dependencies point inward.

```
presentation  ->  infrastructure  ->  application  ->  domain
```

`domain` imports nothing from this project and no framework at all. `application`
defines ports (`Protocol`s) that `infrastructure` implements. `presentation` is a
delivery mechanism and holds no rules.

Enforced three ways, all in CI:

1. `import-linter` layer + forbidden-module contracts (`pyproject.toml`).
2. `tests/architecture/test_layering.py`, which parses the AST of every module.
3. Ruff's `TID` rules banning relative imports, which are how layer violations
   usually sneak in.

## Why a modular monolith

One codebase, one migration history, one image - deployed as several processes
(`api`, `bot`, and later `worker`, `beat`) that scale independently. Bounded
contexts are isolated by package and by the layering contracts, so extracting one
into a service later is mechanical rather than archaeological. Microservices at
this scale would buy distributed debugging and buy nothing else.

## Composition root

`infrastructure/di/container.py` is the only place that knows how to construct a
concrete adapter. It builds a frozen `Container` dataclass holding process-wide
objects (settings, engine, session factory, Redis, clock, health probes) and
exposes factories for request-scoped ones (`unit_of_work()`).

It is intentionally hand-written:

- ~80 lines, fully typed, no framework vocabulary to learn;
- construction order is explicit, so a startup failure has an obvious cause;
- tests assemble a `Container` of fakes with no override machinery.

Building the container performs **no I/O**. Connections are established lazily on
first use, which keeps startup fast and makes readiness - not liveness - the
signal for a dependency outage.

## Request lifecycle (HTTP)

```
Nginx  ->  sets X-Request-ID, rate limits, security headers
  CorrelationIdMiddleware  ->  adopts or mints the id, echoes it back
    AccessLogMiddleware    ->  one structured line per request
      route -> FastAPI dependency -> Container -> UnitOfWork -> session
        exception handlers -> RFC 9457 problem+json, correlation id included
```

## Update lifecycle (Telegram)

```
Telegram  ->  Nginx /telegram/  ->  bot service
  secret-token constant-time comparison (reject before parsing)
    Update.model_validate
      CorrelationIdMiddleware -> LoggingMiddleware -> Router -> handler
```

Webhook only. Polling cannot run in more than one replica and silently drops
updates on restart. The endpoint always answers `200` after feeding the update,
because Telegram retries any non-2xx and a handler bug must not become an
infinite redelivery loop; failures surface in the logs instead.

FSM state lives in Redis, not memory, so a deploy does not drop users mid-flow.

## Health checks

| Endpoint | Question | On failure |
| --- | --- | --- |
| `/health/live` | is the process running? | restart the container |
| `/health/ready` | can it serve traffic? | remove from rotation, do **not** restart |

Probes are time-boxed (2s) and never raise - a failure is a `ProbeResult`, not an
exception. They run concurrently, so readiness latency is the slowest probe, not
their sum. Conflating liveness and readiness causes restart storms during a
database blip; that is why they are separate.

## Errors

`DomainError` and its subclasses are the vocabulary of expected failures.
Infrastructure exceptions are *not* domain errors - they propagate and become a
`500` with a correlation id, and the detail is logged rather than returned.

Every error response is RFC 9457 `application/problem+json` with the same shape,
so the bot, the Mini App and the admin panel parse one thing.

## Events

`AggregateRoot.record()` stores events; the unit of work drains them after a
successful commit. From Phase 2 the drain writes to a Postgres outbox table in the
same transaction as the state change - no dual write, therefore no lost or
phantom events, and no message broker to operate.

## Deferred deliberately

Prometheus metrics, Celery worker and beat, the outbox dispatcher, and the panel
adapter layer are Phase 1.5-2. The seams exist (`entrypoints/`, ports, container)
so adding them touches no existing business code - there is none yet.
