"""Panel accounts of long-dead services are removed after the operator's grace."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.application.provisioning.expired_cleanup import CLEANUP_REASON_FA, ExpiredCleanup
from geekvpn.domain.provisioning import Subscription
from tests.unit.provisioning.fakes import FrozenClock

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def lapsed(sid: str) -> Subscription:
    return Subscription.activate(
        sid,
        user_id=1,
        order_id="o",
        plan_id="p",
        remote_username=sid,
        now=NOW - timedelta(days=40),
        duration_days=30,
    )


class Lapsed:
    def __init__(self, *subs: Subscription) -> None:
        self.subs = list(subs)
        self.cutoff: datetime | None = None

    async def list_lapsed_before(
        self, *, cutoff: datetime, limit: int = 200
    ) -> Sequence[Subscription]:
        self.cutoff = cutoff
        return self.subs


async def run(hours: int, *subs: Subscription, failing: str = "") -> tuple[list[str], Lapsed]:
    revoked: list[str] = []
    source = Lapsed(*subs)

    async def revoke(sid: str, reason: str) -> None:
        assert reason == CLEANUP_REASON_FA
        if sid == failing:
            raise RuntimeError("panel down")
        revoked.append(sid)

    async def grace() -> int:
        return hours

    removed = await ExpiredCleanup(
        lapsed=source, revoke=revoke, hours=grace, clock=FrozenClock(NOW)
    ).run()
    assert [s.id for s in removed] == revoked
    return revoked, source


async def test_services_past_the_grace_period_are_revoked() -> None:
    revoked, source = await run(48, lapsed("a"), lapsed("b"))

    assert revoked == ["a", "b"]
    assert source.cutoff == NOW - timedelta(hours=48)


async def test_zero_hours_keeps_everything() -> None:
    revoked, source = await run(0, lapsed("a"))

    assert revoked == []
    assert source.cutoff is None


async def test_one_panel_failing_does_not_stop_the_rest() -> None:
    revoked, _ = await run(48, lapsed("a"), lapsed("b"), failing="a")

    assert revoked == ["b"]
