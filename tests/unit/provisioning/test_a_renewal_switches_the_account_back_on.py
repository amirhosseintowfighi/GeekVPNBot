"""A renewal has to leave the panel account switched on, not only extended.

Reported from production: a customer renewed and their client said the
service was disabled. When a service runs out of days or traffic the panel
takes the account out of service itself - Marzban marks it `expired` or
`limited`, 3x-ui clears the client's `enable` flag - and renewal only ever
wrote a new date and a new cap. Marzban usually works its own status out again
from those; 3x-ui never does, and Marzban does not either for an account that
was `limited` when the counter cannot be reset. The money was taken, the date
moved, and the link kept serving the "service disabled" placeholder.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.application.provisioning.provisioning_service import ProvisioningService
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.panels.enums import AccountState
from geekvpn.domain.panels.values import AccountUsage, PanelAccount, PanelAccountRef
from geekvpn.domain.provisioning.enums import OrderState, SubscriptionState
from geekvpn.domain.provisioning.order import Order
from geekvpn.domain.provisioning.subscription import Subscription
from tests.unit.provisioning.fakes import (
    FakePanel,
    FakePanelProvider,
    FrozenClock,
    InMemoryNodes,
    InMemoryOrders,
    InMemorySubscriptions,
    RecordingPublisher,
    SequentialIds,
    node,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


class PanelThatLeavesItOff(FakePanel):
    """Extends the account but reports it still out of service, as 3x-ui does
    for a client whose `enable` flag it cleared on expiry."""

    def __init__(self, *, state_after_renew: AccountState) -> None:
        super().__init__()
        self._state_after_renew = state_after_renew
        self.resumed: list[str] = []

    async def renew(self, ref: PanelAccountRef, **kwargs: object) -> PanelAccount:
        self.renewed.append(ref)
        return PanelAccount(
            ref=ref,
            state=self._state_after_renew,
            usage=AccountUsage(used_bytes=0, measured_at=NOW),
        )

    async def resume(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        self.resumed.append(idempotency_key)
        return PanelAccount(
            ref=ref, state=AccountState.ACTIVE, usage=AccountUsage(used_bytes=0, measured_at=NOW)
        )


def _expired_subscription() -> Subscription:
    return Subscription(
        "sub-1",
        user_id=777,
        order_id="order-old",
        plan_id="plan-1",
        started_at=NOW - timedelta(days=35),
        expires_at=NOW - timedelta(days=5),
        remote_username="amir",
        state=SubscriptionState.EXPIRED,
        node_id="node-de",
        traffic_limit_mib=20 * 1024,
        traffic_used_mib=20 * 1024,
    )


def _renewal() -> Order:
    order = Order.place(
        "ord-renew",
        number="1405-0002",
        user_id=777,
        plan_id="plan-1",
        plan_name_fa="۲۰ گیگ یک‌ماهه",
        duration_days=30,
        list_price=Money(120_000),
        total=Money(120_000),
        now=NOW,
        traffic_mib=20 * 1024,
        device_limit=2,
        is_renewal=True,
        renews_subscription_id="sub-1",
    )
    order.mark_paid(at=NOW, invoice_id="inv-2")
    order.collect_events()
    return order


async def _renew_on(panel: FakePanel) -> InMemoryOrders:
    order = _renewal()
    orders = InMemoryOrders(order)
    subscriptions = InMemorySubscriptions()
    await subscriptions.add(_expired_subscription())
    service = ProvisioningService(
        orders=orders,
        subscriptions=subscriptions,
        nodes=InMemoryNodes(node("node-de")),
        panels=FakePanelProvider(panel),
        clock=FrozenClock(NOW),
        ids=SequentialIds("sub"),
        events=RecordingPublisher(),
    )
    await service.provision(order.id)
    return orders


@pytest.mark.parametrize(
    "left_as",
    [AccountState.SUSPENDED, AccountState.EXPIRED, AccountState.QUOTA_EXHAUSTED],
)
async def test_an_account_the_panel_left_switched_off_is_switched_back_on(
    left_as: AccountState,
) -> None:
    panel = PanelThatLeavesItOff(state_after_renew=left_as)

    orders = await _renew_on(panel)

    assert panel.resumed == ["ord-renew:resume"]
    assert orders.rows["ord-renew"].state is OrderState.ACTIVE


async def test_an_account_already_back_in_service_is_left_alone() -> None:
    """No extra write when the panel did its own bookkeeping: a resume on
    Marzban rewrites the status field, and that is one more call to fail."""
    panel = PanelThatLeavesItOff(state_after_renew=AccountState.ACTIVE)

    await _renew_on(panel)

    assert panel.resumed == []
