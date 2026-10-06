"""Scheduled jobs only exist if the worker runs them.

This project's recurring failure was code that worked and that nothing called.
These pin that auto-renewal and backups are on the worker's table, and that a
job which throws does not take the rest of the tick with it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from geekvpn.entrypoints.worker import Worker
from geekvpn.infrastructure.backup.service import is_due

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def test_auto_renewal_and_backups_are_scheduled() -> None:
    worker = Worker(SimpleNamespace())  # type: ignore[arg-type]

    assert {name for name, _, _ in worker._periodic} >= {"auto_renew", "backup"}


async def test_one_failing_job_does_not_stop_the_next() -> None:
    worker = Worker(SimpleNamespace())  # type: ignore[arg-type]
    ran: list[str] = []

    async def broken() -> None:
        ran.append("broken")
        raise RuntimeError("panel down")

    async def healthy() -> None:
        ran.append("healthy")

    worker._periodic = [("broken", 60, broken), ("healthy", 60, healthy)]
    await worker._run_periodic()

    assert ran == ["broken", "healthy"]


async def test_a_job_waits_for_its_interval() -> None:
    worker = Worker(SimpleNamespace())  # type: ignore[arg-type]
    ran: list[str] = []

    async def job() -> None:
        ran.append("x")

    worker._periodic = [("job", 3600, job)]
    await worker._run_periodic()
    await worker._run_periodic()

    assert ran == ["x"]


def test_a_backup_is_due_once_the_interval_has_passed() -> None:
    assert is_due(None, now=NOW, interval_hours=24)
    assert not is_due(NOW - timedelta(hours=23), now=NOW, interval_hours=24)
    assert is_due(NOW - timedelta(hours=24), now=NOW, interval_hours=24)
