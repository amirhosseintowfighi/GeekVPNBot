"""Renewing from the wallet, for customers who asked for it.

Once per expiry, whatever happens: a wallet that is short is told once, not on
every tick until the service dies, and a charge is never retried by a loop
that might take the money twice.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.application.provisioning.auto_renewal import (
    AutoRenewal,
    ChargeResult,
    RenewalOutcome,
)
from geekvpn.domain.notifications.message import RenderedMessage
from geekvpn.domain.provisioning import Subscription

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


def ending_soon(sub_id: str = "sub-1") -> Subscription:
    sub = Subscription.activate(
        sub_id,
        user_id=1001,
        order_id="ord-1",
        plan_id="plan-30",
        remote_username="gv_1001",
        now=NOW - timedelta(days=30) + timedelta(hours=5),
        duration_days=30,
    )
    sub.set_auto_renew(True)
    return sub


class Candidates:
    def __init__(self, *subs: Subscription) -> None:
        self.subs = list(subs)
        self.asked_before: datetime | None = None

    async def list_auto_renew_due(
        self, *, before: datetime, limit: int = 200
    ) -> Sequence[Subscription]:
        self.asked_before = before
        return self.subs


class Attempts:
    def __init__(self) -> None:
        self.keys: set[str] = set()

    async def seen(self, key: str) -> bool:
        return key in self.keys

    async def mark(self, key: str) -> None:
        self.keys.add(key)


class World:
    def __init__(self, *subs: Subscription, result: ChargeResult, enabled: bool = True) -> None:
        self.charged: list[str] = []
        self.told: list[tuple[int, RenderedMessage]] = []
        self.result = result
        self.enabled = enabled
        self.candidates = Candidates(*subs)
        self.attempts = Attempts()

        async def charge(sub: Subscription) -> ChargeResult:
            self.charged.append(sub.id)
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

        async def notify(sub: Subscription, message: RenderedMessage) -> None:
            self.told.append((sub.user_id, message))

        async def is_enabled() -> bool:
            return self.enabled

        self.service = AutoRenewal(
            candidates=self.candidates,
            charge=charge,
            attempts=self.attempts,
            notify=notify,
            enabled=is_enabled,
            clock=Clock(),
        )


async def test_a_service_ending_within_a_day_is_renewed_and_its_owner_told() -> None:
    world = World(ending_soon(), result=ChargeResult(RenewalOutcome.RENEWED, amount=900_000))

    report = await world.service.run()

    assert report.renewed == 1
    assert world.charged == ["sub-1"]
    assert world.candidates.asked_before == NOW + timedelta(hours=24)
    [(user_id, message)] = world.told
    assert user_id == 1001
    assert message.key == "renewal.auto_done"


async def test_each_expiry_is_attempted_once() -> None:
    world = World(ending_soon(), result=ChargeResult(RenewalOutcome.SHORT, amount=50_000))

    await world.service.run()
    await world.service.run()

    assert world.charged == ["sub-1"]
    assert [m.key for _, m in world.told] == ["renewal.auto_short"]


async def test_a_short_wallet_is_told_how_much_is_missing() -> None:
    world = World(ending_soon(), result=ChargeResult(RenewalOutcome.SHORT, amount=50_000))

    await world.service.run()

    [(_, message)] = world.told
    assert "۵۰" in message.body_fa


async def test_the_operators_switch_stops_every_renewal() -> None:
    world = World(ending_soon(), result=ChargeResult(RenewalOutcome.RENEWED), enabled=False)

    report = await world.service.run()

    assert world.charged == []
    assert report.examined == 0


async def test_a_charge_that_crashes_is_reported_and_not_retried() -> None:
    world = World(ending_soon(), result=RuntimeError("panel down"))  # type: ignore[arg-type]

    first = await world.service.run()
    await world.service.run()

    assert first.failed == 1
    assert world.charged == ["sub-1"]
    assert [m.key for _, m in world.told] == ["renewal.auto_failed"]


async def test_one_customer_failing_does_not_stop_the_next() -> None:
    world = World(
        ending_soon("sub-1"), ending_soon("sub-2"), result=RuntimeError("boom")  # type: ignore[arg-type]
    )

    await world.service.run()

    assert world.charged == ["sub-1", "sub-2"]
