"""Probes report failure; they never raise and never hang."""

from __future__ import annotations

import asyncio

import pytest

from geekvpn.infrastructure.health.probes import DatabaseProbe, RedisProbe, run_probes

pytestmark = pytest.mark.unit


class _ExplodingEngine:
    def connect(self) -> object:
        raise ConnectionError("could not connect to server")


class _HangingRedis:
    async def ping(self) -> None:
        await asyncio.sleep(10)


class _HealthyRedis:
    async def ping(self) -> bool:
        return True


async def test_database_probe_reports_failure_instead_of_raising() -> None:
    result = await DatabaseProbe(_ExplodingEngine()).check()  # type: ignore[arg-type]

    assert result.healthy is False
    assert result.name == "postgres"
    assert "ConnectionError" in (result.error or "")


async def test_redis_probe_times_out_rather_than_hanging() -> None:
    result = await RedisProbe(_HangingRedis(), timeout=0.05).check()  # type: ignore[arg-type]

    assert result.healthy is False
    assert "TimeoutError" in (result.error or "")


async def test_healthy_probe_reports_latency() -> None:
    result = await RedisProbe(_HealthyRedis()).check()  # type: ignore[arg-type]

    assert result.healthy is True
    assert result.error is None
    assert result.latency_ms >= 0


async def test_run_probes_executes_concurrently() -> None:
    class _Slow:
        name = "slow"

        async def check(self):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.1)
            return await RedisProbe(_HealthyRedis()).check()

    started = asyncio.get_running_loop().time()
    results = await run_probes([_Slow(), _Slow(), _Slow()])  # type: ignore[list-item]
    elapsed = asyncio.get_running_loop().time() - started

    assert len(results) == 3
    assert elapsed < 0.25, "probes must run concurrently, not sequentially"


async def test_run_probes_with_no_probes() -> None:
    assert await run_probes([]) == []
