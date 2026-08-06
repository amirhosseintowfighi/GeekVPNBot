"""Readiness probes for Postgres and Redis.

Design notes:
* Each probe is time-boxed. A readiness endpoint that hangs is worse than one
  that reports failure, because the orchestrator cannot make a decision.
* Probes never raise. Failure is data.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from geekvpn.application.ports.health import HealthProbe, ProbeResult

DEFAULT_TIMEOUT_SECONDS = 2.0


class DatabaseProbe:
    name = "postgres"

    def __init__(self, engine: AsyncEngine, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._engine = engine
        self._timeout = timeout

    async def check(self) -> ProbeResult:
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self._timeout), self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            return _failure(self.name, started, exc)
        return _success(self.name, started)


class RedisProbe:
    name = "redis"

    def __init__(self, client: Redis, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._client = client
        self._timeout = timeout

    async def check(self) -> ProbeResult:
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self._timeout):
                await self._client.ping()
        except Exception as exc:
            return _failure(self.name, started, exc)
        return _success(self.name, started)


async def run_probes(probes: Sequence[HealthProbe]) -> list[ProbeResult]:
    """Run every probe concurrently. Total latency is the slowest probe."""
    if not probes:
        return []
    return list(await asyncio.gather(*(probe.check() for probe in probes)))


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _success(name: str, started: float) -> ProbeResult:
    return ProbeResult(name=name, healthy=True, latency_ms=_elapsed_ms(started))


def _failure(name: str, started: float, exc: BaseException) -> ProbeResult:
    return ProbeResult(
        name=name,
        healthy=False,
        latency_ms=_elapsed_ms(started),
        error=f"{type(exc).__name__}: {exc}",
    )
