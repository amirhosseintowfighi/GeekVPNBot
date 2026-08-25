"""Operator actions must reach the panel before they change our record.

The order is the whole safety property. Change our row first and a panel that
refuses leaves a subscription marked suspended while the account it names keeps
carrying traffic - the customer is cut off in the panel nobody looks at, or not
cut off at all, and the two only disagree until somebody checks by hand.

Panel first means a failure changes nothing: the operator sees the error and
the subscription still says what it said before.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from geekvpn.application.provisioning.subscription_admin import (
    MIB_PER_GIB,
    SubscriptionAdminService,
)
from geekvpn.domain.panels.errors import PanelError
from geekvpn.domain.provisioning.enums import SubscriptionState
from geekvpn.domain.provisioning.errors import SubscriptionNotFound
from geekvpn.domain.provisioning.subscription import Subscription

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class Adapter:
    """Records what it was asked to do, and can refuse."""

    def __init__(self, *, refuses: bool = False) -> None:
        self.calls: list[str] = []
        self._refuses = refuses

    def _record(self, name: str) -> None:
        self.calls.append(name)
        if self._refuses:
            raise PanelError("The panel refused.")

    async def suspend(self, ref: object, *, idempotency_key: str) -> None:
        self._record("suspend")

    async def resume(self, ref: object, *, idempotency_key: str) -> None:
        self._record("resume")

    async def delete_account(self, ref: object, *, idempotency_key: str) -> None:
        self._record("delete_account")

    async def renew(self, ref: object, **kwargs: object) -> None:
        self._record("renew")

    async def reset_traffic(self, ref: object, *, idempotency_key: str) -> None:
        self._record("reset_traffic")


class Subscriptions:
    def __init__(self, subscription: Subscription | None) -> None:
        self._subscription = subscription
        self.saved = 0

    async def get(self, subscription_id: str) -> Subscription | None:
        if self._subscription is None or self._subscription.id != subscription_id:
            return None
        return self._subscription

    async def update(self, subscription: Subscription) -> None:
        self.saved += 1


class Nodes:
    async def get(self, node_id: str) -> object | None:
        return object()


class Panels:
    def __init__(self, adapter: Adapter) -> None:
        self.adapter = adapter

    async def for_node(self, node: object) -> Adapter:
        return self.adapter


def make_subscription(**overrides: object) -> Subscription:
    fields: dict[str, object] = {
        "user_id": 87791922,
        "order_id": "ord-1",
        "plan_id": "plan-1",
        "state": SubscriptionState.ACTIVE,
        "node_id": "node-1",
        "remote_username": "geek-1405-00009",
        "remote_id": None,
        "subscription_url": None,
        "started_at": NOW,
        "expires_at": datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
        "traffic_limit_mib": 50 * MIB_PER_GIB,
        "traffic_used_mib": 0,
        "device_limit": 2,
    }
    fields.update(overrides)
    return Subscription.restore("sub-1", **fields)


def build(
    subscription: Subscription | None = None, *, refuses: bool = False
) -> tuple[SubscriptionAdminService, Subscriptions, Adapter]:
    subscriptions = Subscriptions(subscription)
    adapter = Adapter(refuses=refuses)
    service = SubscriptionAdminService(
        subscriptions=subscriptions,  # type: ignore[arg-type]
        nodes=Nodes(),  # type: ignore[arg-type]
        panels=Panels(adapter),  # type: ignore[arg-type]
        clock=FrozenClock(),  # type: ignore[arg-type]
    )
    return service, subscriptions, adapter


async def test_suspending_reaches_the_panel_and_then_the_record() -> None:
    subscription = make_subscription()
    service, subscriptions, adapter = build(subscription)

    await service.suspend("sub-1", reason_fa="اشتراک‌گذاری لینک")

    assert adapter.calls == ["suspend"]
    assert subscription.state is SubscriptionState.SUSPENDED
    assert subscriptions.saved == 1


async def test_a_refusing_panel_leaves_the_subscription_untouched() -> None:
    """The property the ordering exists for."""
    subscription = make_subscription()
    service, subscriptions, _ = build(subscription, refuses=True)

    with pytest.raises(PanelError):
        await service.suspend("sub-1", reason_fa="اشتراک‌گذاری لینک")

    assert subscription.state is SubscriptionState.ACTIVE
    assert subscriptions.saved == 0


async def test_revoking_deletes_the_account_rather_than_disabling_it() -> None:
    subscription = make_subscription()
    service, _, adapter = build(subscription)

    await service.revoke("sub-1", reason_fa="بازگشت وجه")

    assert adapter.calls == ["delete_account"]
    assert subscription.state is SubscriptionState.REVOKED
    assert subscription.revoked_at == NOW


async def test_the_row_survives_a_revoke() -> None:
    """An order, a payment and any refund all point at it."""
    subscription = make_subscription()
    service, subscriptions, _ = build(subscription)

    await service.revoke("sub-1", reason_fa="بازگشت وجه")

    assert await subscriptions.get("sub-1") is subscription


async def test_added_traffic_is_converted_from_gib() -> None:
    """Operators think in GiB; the aggregate stores MiB."""
    subscription = make_subscription(traffic_limit_mib=50 * MIB_PER_GIB)
    service, _, adapter = build(subscription)

    await service.add_traffic("sub-1", gib=20)

    assert subscription.traffic_limit_mib == 70 * MIB_PER_GIB
    assert adapter.calls == ["renew"]


async def test_extending_moves_the_expiry() -> None:
    subscription = make_subscription()
    service, _, adapter = build(subscription)
    before = subscription.expires_at

    await service.extend("sub-1", days=7)

    assert subscription.expires_at > before
    assert adapter.calls == ["renew"]


async def test_an_unknown_subscription_is_reported_not_guessed() -> None:
    service, _, _ = build(None)

    with pytest.raises(SubscriptionNotFound):
        await service.resume("sub-1")


async def test_a_subscription_with_no_panel_account_can_still_be_closed() -> None:
    """Otherwise the records most in need of tidying are the ones that cannot be."""
    subscription = make_subscription(node_id=None, remote_username=None)
    service, subscriptions, adapter = build(subscription)

    await service.revoke("sub-1", reason_fa="هرگز ساخته نشد")

    assert adapter.calls == []
    assert subscription.state is SubscriptionState.REVOKED
    assert subscriptions.saved == 1
