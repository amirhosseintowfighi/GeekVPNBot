"""What an operator changes on the panel is what the bot and the app show.

An operator raised a customer's volume on the panel from 30GB to 120GB and
reset the usage; the bot and the app went on saying the service was used up.
The sweep read one number back - the usage - and nothing else, so the 30GB
cap stayed in our row for good. And the usage only ever went up: a panel
reporting less than we held was ignored, so the reset never arrived either.

The panel is where the account lives and what enforces it, so its reading is
the truth: the cap, the usage even when it went down, and the state those
two imply. And 3x-ui panels, which have no batched usage call, are read one
account at a time instead of failing the whole node every tick.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from geekvpn.application.provisioning.ports import NodeRecord
from geekvpn.application.provisioning.usage_sync import BYTES_PER_MIB, UsageSyncService
from geekvpn.domain.panels.enums import AccountState, Capability, PanelKind
from geekvpn.domain.panels.errors import CapabilityNotSupported
from geekvpn.domain.panels.values import AccountUsage, PanelAccount, TrafficQuota
from geekvpn.domain.provisioning.enums import NodeState, SubscriptionState
from geekvpn.domain.provisioning.subscription import Subscription

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 13, tzinfo=UTC)
GIB_MIB = 1024
GIB = 1024**3


class _Clock:
    def now(self) -> datetime:
        return NOW


def _node(node_id: str = "n1") -> NodeRecord:
    return NodeRecord(
        id=node_id,
        name_fa="آلمان",
        panel_kind=PanelKind.MARZBAN,
        state=NodeState.ONLINE,
        accepting_new=True,
        capacity=0,
        account_count=0,
    )


def _exhausted(sub_id: str = "s1", *, username: str = "amir") -> Subscription:
    """30GB, all of it used, as the bot held it before the operator's edit."""
    return Subscription(
        sub_id,
        user_id=1,
        order_id=f"o-{sub_id}",
        plan_id="p",
        state=SubscriptionState.EXHAUSTED,
        node_id="n1",
        remote_username=username,
        started_at=NOW,
        expires_at=datetime(2026, 12, 13, tzinfo=UTC),
        traffic_limit_mib=30 * GIB_MIB,
        traffic_used_mib=30 * GIB_MIB,
        device_limit=1,
    )


class _Subscriptions:
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


class _Nodes:
    async def get(self, node_id: str) -> NodeRecord | None:
        return _node(node_id)


class _Panel:
    """A panel holding (used bytes, cap bytes or None) per account."""

    def __init__(self, accounts: dict[str, tuple[int, int | None]], *, bulk: bool = True) -> None:
        self.accounts = accounts
        self.capabilities = frozenset({Capability.BULK_USAGE} if bulk else set())
        self.bulk_calls = 0
        self.single_calls = 0

    def _usage(self, username: str) -> AccountUsage:
        used, cap = self.accounts[username]
        return AccountUsage(used_bytes=used, measured_at=NOW, quota=TrafficQuota(cap))

    async def bulk_usage(self, refs):
        if Capability.BULK_USAGE not in self.capabilities:
            raise CapabilityNotSupported("no bulk", panel="3x-ui", capability="bulk_usage")
        self.bulk_calls += 1
        return {r.username: self._usage(r.username) for r in refs if r.username in self.accounts}

    async def get_account(self, ref):
        self.single_calls += 1
        return PanelAccount(ref=ref, state=AccountState.ACTIVE, usage=self._usage(ref.username))


class _Panels:
    def __init__(self, panel: _Panel) -> None:
        self.panel = panel

    async def for_node(self, node: NodeRecord) -> _Panel:
        return self.panel


def _service(subs: list[Subscription], panel: _Panel) -> tuple[UsageSyncService, _Subscriptions]:
    store = _Subscriptions(subs)
    return (
        UsageSyncService(
            subscriptions=store, nodes=_Nodes(), panels=_Panels(panel), clock=_Clock()
        ),
        store,
    )


async def test_a_volume_raised_and_reset_on_the_panel_brings_the_service_back() -> None:
    panel = _Panel({"amir": (0, 120 * GIB)})
    service, store = _service([_exhausted()], panel)

    await service.sync_all()

    sub = store.items["s1"]
    assert sub.traffic_limit_mib == 120 * GIB_MIB
    assert sub.traffic_used_mib == 0
    assert sub.state is SubscriptionState.ACTIVE


async def test_a_volume_raised_without_a_reset_is_no_longer_used_up() -> None:
    panel = _Panel({"amir": (30 * GIB, 120 * GIB)})
    service, store = _service([_exhausted()], panel)

    await service.sync_all()

    sub = store.items["s1"]
    assert sub.traffic_limit_mib == 120 * GIB_MIB
    assert sub.state is SubscriptionState.ACTIVE
    assert sub.remaining_mib == 90 * GIB_MIB


async def test_a_volume_lowered_on_the_panel_is_used_up_here_too() -> None:
    fresh = _exhausted()
    fresh.reset_traffic(at=NOW)
    panel = _Panel({"amir": (10 * GIB, 10 * GIB)})
    service, store = _service([fresh], panel)

    await service.sync_all()

    sub = store.items["s1"]
    assert sub.traffic_limit_mib == 10 * GIB_MIB
    assert sub.state is SubscriptionState.EXHAUSTED


async def test_a_panel_account_made_unlimited_is_unlimited_here() -> None:
    panel = _Panel({"amir": (30 * GIB, None)})
    service, store = _service([_exhausted()], panel)

    await service.sync_all()

    sub = store.items["s1"]
    assert sub.is_unlimited
    assert sub.state is SubscriptionState.ACTIVE


async def test_a_reset_lets_the_usage_warnings_fire_again() -> None:
    sub = _exhausted()
    sub.mark_traffic_notified(80)
    panel = _Panel({"amir": (0, 30 * GIB)})
    service, store = _service([sub], panel)

    await service.sync_all()

    assert 80 not in store.items["s1"].notified_traffic_percents


async def test_the_sync_now_button_reads_the_cap_as_well() -> None:
    panel = _Panel({"amir": (0, 120 * GIB)})
    service, store = _service([_exhausted()], panel)

    await service.sync_subscription("s1")

    sub = store.items["s1"]
    assert sub.traffic_limit_mib == 120 * GIB_MIB
    assert sub.state is SubscriptionState.ACTIVE


async def test_a_panel_without_batched_usage_is_read_account_by_account() -> None:
    """3x-ui has no batched call; the node used to fail every tick instead."""
    panel = _Panel({"amir": (0, 120 * GIB), "sara": (5 * GIB, 50 * GIB)}, bulk=False)
    service, store = _service([_exhausted("s1"), _exhausted("s2", username="sara")], panel)

    report = await service.sync_all()

    assert report.failed_nodes == []
    assert report.updated == 2
    assert panel.single_calls == 2
    assert store.items["s2"].traffic_used_mib == 5 * GIB // BYTES_PER_MIB


async def test_every_account_on_a_large_node_is_read() -> None:
    """Only the first page of a node's accounts was ever asked for."""
    names = [f"u{i}" for i in range(7)]
    subs = [_exhausted(f"s{i}", username=name) for i, name in enumerate(names)]
    panel = _Panel(dict.fromkeys(names, (0, 120 * GIB)))
    service, store = _service(subs, panel)

    await service.sync_all(batch_size=3)

    assert all(s.state is SubscriptionState.ACTIVE for s in store.items.values())
    assert panel.bulk_calls == 3
