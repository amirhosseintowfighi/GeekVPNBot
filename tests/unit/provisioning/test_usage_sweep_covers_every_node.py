"""The usage sweep visits nodes that hold accounts, not nodes we can sell on.

`sync_all` walked `list_sellable()`, which answers a different question: where
would a *new* account go. The moment an operator stopped selling from a node -
full, draining, in maintenance - every paying customer already on it stopped
having their traffic read. Their figure froze at whatever it was that day, the
admin panel showed a stale number forever, and because the quota warnings are
computed from that figure, their 80% notice stopped firing too.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.application.provisioning.usage_sync import BYTES_PER_MIB, UsageSyncService
from geekvpn.domain.panels.values import AccountUsage
from geekvpn.domain.provisioning.subscription import Subscription

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 3, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeSubscriptions:
    def __init__(self, subs: list[Subscription]) -> None:
        self.items = {s.id: s for s in subs}

    async def get(self, subscription_id: str) -> Subscription | None:
        return self.items.get(subscription_id)

    async def search(self, *, node_id=None, **_kw):
        found = [s for s in self.items.values() if node_id in (None, s.node_id)]
        return found, len(found)

    async def update(self, subscription: Subscription) -> None:
        self.items[subscription.id] = subscription

    async def node_ids_with_accounts(self):
        return sorted({s.node_id for s in self.items.values() if s.node_id})


class FakeNode:
    def __init__(self, node_id: str) -> None:
        self.id = node_id


class FakeNodes:
    """`list_sellable` deliberately answers with less than `get` knows about.

    That gap is the bug: a node can hold customers long after it stops taking
    new ones.
    """

    def __init__(self, *, all_ids: list[str], sellable_ids: list[str]) -> None:
        self._all = all_ids
        self._sellable = sellable_ids
        self.sellable_calls = 0

    async def get(self, node_id: str):
        return FakeNode(node_id) if node_id in self._all else None

    async def list_sellable(self):
        self.sellable_calls += 1
        return [FakeNode(n) for n in self._sellable]


class FakeAdapter:
    def __init__(self, used_mib: int) -> None:
        self._used = used_mib

    async def bulk_usage(self, refs):
        return {
            ref.username: AccountUsage(
                used_bytes=self._used * BYTES_PER_MIB, measured_at=NOW
            )
            for ref in refs
        }


class FakePanels:
    def __init__(self, used_mib: int) -> None:
        self._used = used_mib

    async def for_node(self, node):
        return FakeAdapter(self._used)


def _subscription(sub_id: str, node_id: str) -> Subscription:
    return Subscription(
        sub_id,
        user_id=1,
        order_id=f"order-{sub_id}",
        plan_id="plan",
        started_at=NOW - timedelta(days=10),
        expires_at=NOW + timedelta(days=20),
        remote_username=f"user-{sub_id}",
        node_id=node_id,
        remote_id=None,
        traffic_limit_mib=10_000,
    )


def _service(subscriptions: FakeSubscriptions, nodes: FakeNodes) -> UsageSyncService:
    return UsageSyncService(
        subscriptions=subscriptions,
        nodes=nodes,
        panels=FakePanels(used_mib=500),
        clock=FixedClock(),
    )


def test_a_node_that_stopped_selling_still_has_its_usage_read():
    """The bug. `full` holds a live customer and takes no new ones."""
    subscriptions = FakeSubscriptions([_subscription("a", "open"), _subscription("b", "full")])
    nodes = FakeNodes(all_ids=["open", "full"], sellable_ids=["open"])

    report = asyncio.run(_service(subscriptions, nodes).sync_all())

    assert report.updated == 2
    assert subscriptions.items["b"].traffic_used_mib == 500


def test_the_sweep_does_not_ask_which_nodes_are_sellable():
    """Naming the mechanism, not just the symptom.

    A future refactor that reintroduces `list_sellable()` here would pass the
    test above only while the fixture happens to mark every node sellable.
    """
    subscriptions = FakeSubscriptions([_subscription("a", "open")])
    nodes = FakeNodes(all_ids=["open"], sellable_ids=["open"])

    asyncio.run(_service(subscriptions, nodes).sync_all())

    assert nodes.sellable_calls == 0


def test_a_node_with_no_accounts_is_not_visited_at_all():
    """The other half: sweeping empty nodes is a round trip for nothing."""
    subscriptions = FakeSubscriptions([_subscription("a", "open")])
    nodes = FakeNodes(all_ids=["open", "empty"], sellable_ids=["open", "empty"])

    report = asyncio.run(_service(subscriptions, nodes).sync_all())

    assert [n.node_id for n in report.nodes] == ["open"]


class ExplodingPanels:
    """Fails the way a real misconfiguration does: not with a `PanelError`.

    Building an adapter decrypts the stored password and validates the config
    payload. A rotated key or a malformed payload raises neither of those as a
    panel error, and the sweep only caught panel errors.
    """

    def __init__(self, broken: str) -> None:
        self._broken = broken

    async def for_node(self, node):
        if node.id == self._broken:
            raise ValueError("could not decrypt node.password")
        return FakeAdapter(500)


def test_one_misconfigured_node_does_not_take_down_the_whole_sweep():
    subscriptions = FakeSubscriptions([_subscription("a", "good"), _subscription("b", "broken")])
    nodes = FakeNodes(all_ids=["good", "broken"], sellable_ids=["good", "broken"])
    service = UsageSyncService(
        subscriptions=subscriptions,
        nodes=nodes,
        panels=ExplodingPanels("broken"),
        clock=FixedClock(),
    )

    report = asyncio.run(service.sync_all())

    assert subscriptions.items["a"].traffic_used_mib == 500
    assert report.failed_nodes == ["broken"]


def test_the_failure_says_what_went_wrong():
    """`worker.tick_failed` named no node. This has to."""
    subscriptions = FakeSubscriptions([_subscription("b", "broken")])
    nodes = FakeNodes(all_ids=["broken"], sellable_ids=["broken"])
    service = UsageSyncService(
        subscriptions=subscriptions,
        nodes=nodes,
        panels=ExplodingPanels("broken"),
        clock=FixedClock(),
    )

    report = asyncio.run(service.sync_all())

    assert "decrypt" in (report.nodes[0].error or "")
