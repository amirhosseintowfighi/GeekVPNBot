"""The expiry the bot shows and the expiry the panel enforces are one date.

A renewal sent the panel a length of time - "add 30 days" - and each side then
added it to its own idea of the current expiry: the panel to the date it held,
the database to the date it held. Any difference between the two survived every
renewal, and grew with some of them:

* an account the operator had extended on the panel was extended from there,
  while the database extended from its older date;
* a Marzban account still "on hold" has no date on the panel, so the panel
  counted from today and the database from the stored date;
* a retry after the panel had already applied a renewal added the days a
  second time on the panel - the adapters do not honour the idempotency key
  for a renewal - and only once in the database.

And a date changed on the panel never came back: the sweep read usage, never
the date, so a service the operator extended there still read "expired".

Now the date is computed once, from the subscription, and written to the panel
as that date. Writing an absolute date is safe to repeat, and both sides hold
the same value by construction. The sweep reads the panel's date back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from geekvpn.application.provisioning.ports import NodeRecord
from geekvpn.application.provisioning.provisioning_service import ProvisioningService
from geekvpn.application.provisioning.subscription_admin import SubscriptionAdminService
from geekvpn.application.provisioning.usage_sync import UsageSyncService
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.panels.enums import AccountState, Capability, PanelKind
from geekvpn.domain.panels.values import AccountUsage, PanelAccount, PanelAccountRef, TrafficQuota
from geekvpn.domain.provisioning.enums import NodeState, SubscriptionState
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

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
GIB = 1024**3


class RecordingPanel(FakePanel):
    def __init__(self) -> None:
        super().__init__()
        self.renew_calls: list[dict[str, Any]] = []

    async def renew(self, ref: PanelAccountRef, **kwargs: Any) -> PanelAccount:
        self.renew_calls.append(kwargs)
        return await super().renew(ref, **kwargs)


def _subscription(*, expires_at: datetime, state: SubscriptionState) -> Subscription:
    return Subscription(
        "sub-1",
        user_id=777,
        order_id="order-old",
        plan_id="plan-1",
        started_at=NOW - timedelta(days=40),
        expires_at=expires_at,
        remote_username="amir",
        state=state,
        node_id="node-de",
        traffic_limit_mib=20 * 1024,
        traffic_used_mib=0,
    )


def _renewal(order_id: str = "ord-renew") -> Order:
    order = Order.place(
        order_id,
        number=f"1405-{order_id}",
        user_id=777,
        plan_id="plan-1",
        plan_name_fa="۲۰ گیگ یک‌ماهه",
        duration_days=30,
        list_price=Money(120_000),
        total=Money(120_000),
        now=NOW,
        traffic_mib=20 * 1024,
        device_limit=1,
        is_renewal=True,
        renews_subscription_id="sub-1",
    )
    order.mark_paid(at=NOW, invoice_id=f"inv-{order_id}")
    order.collect_events()
    return order


async def _renew(subscription: Subscription, *orders: Order) -> tuple[RecordingPanel, Subscription]:
    panel = RecordingPanel()
    subscriptions = InMemorySubscriptions()
    await subscriptions.add(subscription)
    store = InMemoryOrders(*orders)
    service = ProvisioningService(
        orders=store,
        subscriptions=subscriptions,
        nodes=InMemoryNodes(node("node-de")),
        panels=FakePanelProvider(panel),
        clock=FrozenClock(NOW),
        ids=SequentialIds("sub"),
        events=RecordingPublisher(),
    )
    for order in orders:
        await service.provision(order.id)
    renewed = await subscriptions.get("sub-1")
    assert renewed is not None
    return panel, renewed


# -- renewal -------------------------------------------------------------------


async def test_renewing_a_live_service_sends_the_panel_the_date_the_bot_shows() -> None:
    panel, renewed = await _renew(
        _subscription(expires_at=NOW + timedelta(days=10), state=SubscriptionState.ACTIVE),
        _renewal(),
    )

    assert renewed.expires_at == NOW + timedelta(days=40)
    assert panel.renew_calls[0]["new_expires_at"] == renewed.expires_at
    assert panel.renew_calls[0].get("extend_by") is None


async def test_renewing_an_expired_service_counts_from_now_on_both_sides() -> None:
    panel, renewed = await _renew(
        _subscription(expires_at=NOW - timedelta(days=5), state=SubscriptionState.EXPIRED),
        _renewal(),
    )

    assert renewed.expires_at == NOW + timedelta(days=30)
    assert panel.renew_calls[0]["new_expires_at"] == renewed.expires_at
    assert renewed.state is SubscriptionState.ACTIVE


async def test_two_renewals_in_a_row_add_up_on_both_sides() -> None:
    panel, renewed = await _renew(
        _subscription(expires_at=NOW + timedelta(days=3), state=SubscriptionState.ACTIVE),
        _renewal("ord-a"),
        _renewal("ord-b"),
    )

    assert renewed.expires_at == NOW + timedelta(days=63)
    assert [c["new_expires_at"] for c in panel.renew_calls] == [
        NOW + timedelta(days=33),
        NOW + timedelta(days=63),
    ]


async def test_renewing_a_moment_before_expiry_keeps_the_remaining_time() -> None:
    panel, renewed = await _renew(
        _subscription(expires_at=NOW + timedelta(seconds=30), state=SubscriptionState.ACTIVE),
        _renewal(),
    )

    assert renewed.expires_at == NOW + timedelta(days=30, seconds=30)
    assert panel.renew_calls[0]["new_expires_at"] == renewed.expires_at


# -- the operator's "extend" ---------------------------------------------------


class _Subs:
    def __init__(self, subscription: Subscription) -> None:
        self.item = subscription

    async def get(self, subscription_id: str) -> Subscription | None:
        return self.item if subscription_id == self.item.id else None

    async def update(self, subscription: Subscription) -> None:
        self.item = subscription


class _Nodes:
    async def get(self, node_id: str) -> NodeRecord | None:
        return node(node_id)


async def test_an_operator_extension_sends_the_panel_the_date_the_bot_shows() -> None:
    panel = RecordingPanel()
    subs = _Subs(_subscription(expires_at=NOW + timedelta(days=2), state=SubscriptionState.ACTIVE))
    service = SubscriptionAdminService(
        subscriptions=subs,  # type: ignore[arg-type]
        nodes=_Nodes(),  # type: ignore[arg-type]
        panels=FakePanelProvider(panel),
        clock=FrozenClock(NOW),
    )

    extended = await service.extend("sub-1", days=7)

    assert extended.expires_at == NOW + timedelta(days=9)
    assert panel.renew_calls[0]["new_expires_at"] == extended.expires_at


# -- the sweep -----------------------------------------------------------------


class _SweepPanel:
    capabilities = frozenset({Capability.BULK_USAGE})

    def __init__(self, expires_at: datetime | None) -> None:
        self._expires_at = expires_at

    async def bulk_usage(self, refs):
        return {
            r.username: AccountUsage(
                used_bytes=0,
                measured_at=NOW,
                quota=TrafficQuota(20 * GIB),
                expires_at=self._expires_at,
            )
            for r in refs
        }

    async def get_account(self, ref):
        return PanelAccount(
            ref=ref,
            state=AccountState.ACTIVE,
            usage=AccountUsage(used_bytes=0, measured_at=NOW, quota=TrafficQuota(20 * GIB)),
            expires_at=self._expires_at,
        )


class _SweepPanels:
    def __init__(self, panel: _SweepPanel) -> None:
        self.panel = panel

    async def for_node(self, node: NodeRecord) -> _SweepPanel:
        return self.panel


class _SweepSubs:
    def __init__(self, subs: list[Subscription]) -> None:
        self.items = {s.id: s for s in subs}

    async def get(self, subscription_id: str) -> Subscription | None:
        return self.items.get(subscription_id)

    async def search(self, *, node_id=None, limit=50, offset=0, **_kw):
        found = [s for s in self.items.values() if node_id in (None, s.node_id)]
        return found[offset : offset + limit], len(found)

    async def node_ids_with_accounts(self):
        return sorted({s.node_id for s in self.items.values() if s.node_id})

    async def update(self, subscription: Subscription) -> None:
        self.items[subscription.id] = subscription


class _SweepNodes:
    async def get(self, node_id: str) -> NodeRecord:
        return NodeRecord(
            id=node_id,
            name_fa="آلمان",
            panel_kind=PanelKind.MARZBAN,
            state=NodeState.ONLINE,
            accepting_new=True,
            capacity=0,
            account_count=0,
        )


def _sweep(subs: list[Subscription], expires_at: datetime | None):
    store = _SweepSubs(subs)
    service = UsageSyncService(
        subscriptions=store,
        nodes=_SweepNodes(),
        panels=_SweepPanels(_SweepPanel(expires_at)),
        clock=FrozenClock(NOW),
    )
    return service, store


async def test_a_date_extended_on_the_panel_brings_an_expired_service_back() -> None:
    service, store = _sweep(
        [_subscription(expires_at=NOW - timedelta(days=1), state=SubscriptionState.EXPIRED)],
        NOW + timedelta(days=30),
    )

    await service.sync_all()

    sub = store.items["sub-1"]
    assert sub.expires_at == NOW + timedelta(days=30)
    assert sub.state is SubscriptionState.ACTIVE


async def test_a_date_shortened_on_the_panel_is_shortened_here() -> None:
    service, store = _sweep(
        [_subscription(expires_at=NOW + timedelta(days=30), state=SubscriptionState.ACTIVE)],
        NOW + timedelta(days=3),
    )

    await service.sync_all()

    assert store.items["sub-1"].expires_at == NOW + timedelta(days=3)


async def test_a_panel_with_no_date_leaves_ours_alone() -> None:
    """On hold, or never expiring: the panel has no date to give, so ours stands."""
    kept = NOW + timedelta(days=12)
    service, store = _sweep([_subscription(expires_at=kept, state=SubscriptionState.ACTIVE)], None)

    await service.sync_all()

    assert store.items["sub-1"].expires_at == kept


async def test_the_sync_now_button_reads_the_date_too() -> None:
    service, store = _sweep(
        [_subscription(expires_at=NOW - timedelta(days=1), state=SubscriptionState.EXPIRED)],
        NOW + timedelta(days=30),
    )

    await service.sync_subscription("sub-1")

    assert store.items["sub-1"].expires_at == NOW + timedelta(days=30)


async def test_a_revoked_service_does_not_stop_the_sweep() -> None:
    """Applying a reading to a revoked row raises; it took the node's sweep with it."""
    revoked = _subscription(expires_at=NOW + timedelta(days=5), state=SubscriptionState.ACTIVE)
    revoked.revoke(reason_fa="حذف", at=NOW)
    live = Subscription(
        "sub-2",
        user_id=778,
        order_id="o2",
        plan_id="plan-1",
        started_at=NOW - timedelta(days=31),
        expires_at=NOW - timedelta(days=1),
        remote_username="sara",
        state=SubscriptionState.EXPIRED,
        node_id="node-de",
        traffic_limit_mib=20 * 1024,
        traffic_used_mib=0,
    )
    service, store = _sweep([revoked, live], NOW + timedelta(days=30))

    report = await service.sync_all()

    assert report.failed_nodes == []
    assert store.items["sub-2"].state is SubscriptionState.ACTIVE
