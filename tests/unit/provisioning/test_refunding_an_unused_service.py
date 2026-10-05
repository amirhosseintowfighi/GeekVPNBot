"""A service that carried no traffic can be returned for its price.

Into the wallet, within the shop's window, and only on the panel's own word
that nothing was used - a stored zero can be an hour old.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.application.provisioning.unused_refund import UnusedRefund
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.provisioning import Subscription
from geekvpn.domain.provisioning.enums import OrderSource, OrderState
from geekvpn.domain.provisioning.errors import RefundNotAllowed
from geekvpn.domain.provisioning.order import Order
from tests.unit.provisioning.fakes import FrozenClock, InMemoryOrders, InMemorySubscriptions

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
OWNER = 1001


async def world(
    *,
    hours_ago: int = 2,
    used_now: int = 0,
    window: int = 24,
    source: OrderSource = OrderSource.BOT,
) -> tuple[UnusedRefund, list[str], Order]:
    calls: list[str] = []
    order = Order.place(
        uuid.uuid4().hex,
        number="1405-00009",
        user_id=OWNER,
        plan_id=str(uuid.uuid4()),
        plan_name_fa="ماهانه",
        duration_days=30,
        list_price=Money(300_000),
        total=Money(300_000),
        source=source,
        now=NOW - timedelta(hours=hours_ago),
    )
    order.mark_paid(at=NOW - timedelta(hours=hours_ago))
    order.start_provisioning()
    sub = Subscription.activate(
        "sub-1",
        user_id=OWNER,
        order_id=order.id,
        plan_id=order.plan_id,
        remote_username="gv_1001",
        now=NOW - timedelta(hours=hours_ago),
        duration_days=30,
    )
    order.mark_active(subscription_id=sub.id, at=NOW - timedelta(hours=hours_ago))
    orders = InMemoryOrders(order)
    subs = InMemorySubscriptions()
    await subs.add(sub)

    async def refresh(subscription_id: str) -> Subscription:
        calls.append("refresh")
        sub.record_usage(used_mib=used_now, at=NOW)
        return sub

    async def revoke(subscription_id: str, reason_fa: str) -> Subscription:
        calls.append("revoke")
        sub.revoke(reason_fa=reason_fa, at=NOW)
        return sub

    async def credit(user_id: int, amount: Money, number: str) -> None:
        calls.append(f"credit:{amount.amount}")

    async def hours() -> int:
        return window

    service = UnusedRefund(
        subscriptions=subs,
        orders=orders,
        refresh_usage=refresh,
        revoke=revoke,
        credit=credit,
        window=hours,
        clock=FrozenClock(NOW),
    )
    return service, calls, order


async def test_an_unused_service_is_revoked_then_paid_back() -> None:
    service, calls, order = await world()

    amount = await service.refund("sub-1", owner=OWNER)

    assert amount == Money(300_000)
    assert calls == ["refresh", "revoke", "credit:300000"]
    assert order.state is OrderState.REFUNDED


async def test_usage_the_panel_reports_now_refuses_it() -> None:
    """The stored figure said zero; the panel says otherwise."""
    service, calls, _ = await world(used_now=5)

    with pytest.raises(RefundNotAllowed):
        await service.refund("sub-1", owner=OWNER)
    assert "revoke" not in calls


async def test_after_the_window_it_is_too_late() -> None:
    service, _, _ = await world(hours_ago=30, window=24)

    with pytest.raises(RefundNotAllowed):
        await service.refund("sub-1", owner=OWNER)


async def test_a_shop_that_switched_it_off_refuses_everything() -> None:
    service, _, _ = await world(window=0)

    with pytest.raises(RefundNotAllowed):
        await service.refund("sub-1", owner=OWNER)


async def test_somebody_elses_service_is_refused() -> None:
    service, _, _ = await world()

    with pytest.raises(RefundNotAllowed):
        await service.refund("sub-1", owner=9999)


async def test_a_trial_has_nothing_to_give_back() -> None:
    service, _, _ = await world(source=OrderSource.TRIAL)

    with pytest.raises(RefundNotAllowed):
        await service.refund("sub-1", owner=OWNER)
