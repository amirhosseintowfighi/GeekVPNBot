"""Reading traffic usage back from the panels.

Nothing else writes ``traffic_used_mib``, so every one of these behaviours is
the difference between a quota that is enforced and a quota that is decorative.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from geekvpn.application.provisioning.ports import NodeRecord
from geekvpn.application.provisioning.usage_sync import BYTES_PER_MIB, UsageSyncService
from geekvpn.domain.panels.enums import AccountState, PanelKind
from geekvpn.domain.panels.errors import AccountNotFound, PanelUnreachable
from geekvpn.domain.panels.values import AccountUsage, PanelAccount
from geekvpn.domain.provisioning.enums import NodeState, SubscriptionState
from geekvpn.domain.provisioning.subscription import Subscription

NOW = datetime(2026, 8, 7, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


def make_node(node_id: str) -> NodeRecord:
    return NodeRecord(
        id=node_id,
        name_fa="فرانکفورت",
        panel_kind=PanelKind.MARZBAN,
        state=NodeState.ONLINE,
        accepting_new=True,
        capacity=0,
        account_count=0,
    )


def make_subscription(sub_id: str, *, node_id: str, username: str) -> Subscription:
    return Subscription(
        sub_id,
        user_id=1,
        order_id=f"ord-{sub_id}",
        plan_id="plan-1",
        state=SubscriptionState.ACTIVE,
        node_id=node_id,
        remote_username=username,
        started_at=NOW,
        expires_at=datetime(2026, 12, 1, tzinfo=UTC),
        traffic_limit_mib=10_000,
        traffic_used_mib=0,
        device_limit=2,
    )


class FakeSubscriptions:
    def __init__(self, subs: list[Subscription]) -> None:
        self.items = {s.id: s for s in subs}
        self.updated: list[str] = []

    async def get(self, subscription_id: str) -> Subscription | None:
        return self.items.get(subscription_id)

    async def search(self, *, node_id=None, **_kw):
        found = [s for s in self.items.values() if node_id in (None, s.node_id)]
        return found, len(found)

    async def node_ids_with_accounts(self):
        # What drives the sweep now: where subscriptions actually are, not
        # where a new one would go.
        return sorted({s.node_id for s in self.items.values() if s.node_id})

    async def update(self, subscription: Subscription) -> None:
        self.updated.append(subscription.id)


class FakeNodes:
    def __init__(self, nodes: list[NodeRecord]) -> None:
        self.items = {n.id: n for n in nodes}

    async def get(self, node_id: str) -> NodeRecord | None:
        return self.items.get(node_id)

    async def list_sellable(self):
        return list(self.items.values())


class FakeAdapter:
    def __init__(
        self, readings: dict[str, int] | None = None, error: Exception | None = None
    ) -> None:
        self._readings = readings or {}
        self._error = error
        self.calls = 0

    async def bulk_usage(self, refs):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return {
            username: AccountUsage(used_bytes=used, measured_at=NOW)
            for username, used in self._readings.items()
        }

    async def get_account(self, ref):
        """One account by name, which is how a single subscription is read now.

        The sweep still goes through `bulk_usage`; reading one used to as well,
        and it silently missed any account past the panel's first page.
        """
        self.calls += 1
        if self._error is not None:
            raise self._error
        if ref.username not in self._readings:
            raise AccountNotFound(panel="fake", username=ref.username)
        return PanelAccount(
            ref=ref,
            state=AccountState.ACTIVE,
            usage=AccountUsage(used_bytes=self._readings[ref.username], measured_at=NOW),
        )


class FakePanels:
    def __init__(self, adapters: dict[str, FakeAdapter]) -> None:
        self.adapters = adapters

    async def for_node(self, node: NodeRecord) -> FakeAdapter:
        return self.adapters[node.id]


def build(subs, nodes, adapters) -> UsageSyncService:
    return UsageSyncService(
        subscriptions=FakeSubscriptions(subs),
        nodes=FakeNodes(nodes),
        panels=FakePanels(adapters),
        clock=FrozenClock(),
    )


async def test_a_reading_in_bytes_is_stored_as_mebibytes() -> None:
    sub = make_subscription("s1", node_id="fra", username="u1")
    service = build([sub], [make_node("fra")], {"fra": FakeAdapter({"u1": 500 * BYTES_PER_MIB})})

    await service.sync_subscription("s1")

    assert sub.traffic_used_mib == 500


async def test_one_batched_request_covers_every_account_on_a_node() -> None:
    """A request per customer would be thousands of round trips per sweep."""
    subs = [make_subscription(f"s{i}", node_id="fra", username=f"u{i}") for i in range(5)]
    adapter = FakeAdapter({f"u{i}": BYTES_PER_MIB for i in range(5)})
    service = build(subs, [make_node("fra")], {"fra": adapter})

    report = await service.sync_node("fra")

    assert adapter.calls == 1
    assert report.updated == 5


async def test_an_unreachable_node_does_not_stop_the_other_nodes() -> None:
    subs = [
        make_subscription("s1", node_id="dead", username="u1"),
        make_subscription("s2", node_id="alive", username="u2"),
    ]
    service = build(
        subs,
        [make_node("dead"), make_node("alive")],
        {
            "dead": FakeAdapter(error=PanelUnreachable("timed out", panel="marzban")),
            "alive": FakeAdapter({"u2": 2 * BYTES_PER_MIB}),
        },
    )

    report = await service.sync_all()

    assert report.failed_nodes == ["dead"]
    assert report.updated == 1
    assert subs[1].traffic_used_mib == 2


async def test_a_subscription_that_was_never_created_on_a_panel_is_skipped() -> None:
    """No remote username means provisioning never finished, so there is no
    reading to fetch - and asking anyway would raise on an empty username."""
    sub = make_subscription("s1", node_id="fra", username="")
    service = build([sub], [make_node("fra")], {"fra": FakeAdapter()})

    assert await service.sync_subscription("s1") is None


async def test_an_unknown_subscription_is_not_an_error() -> None:
    service = build([], [make_node("fra")], {"fra": FakeAdapter()})

    assert await service.sync_subscription("missing") is None


@pytest.mark.parametrize("used_bytes", [0, BYTES_PER_MIB - 1])
async def test_a_reading_below_one_mebibyte_records_zero(used_bytes: int) -> None:
    sub = make_subscription("s1", node_id="fra", username="u1")
    service = build([sub], [make_node("fra")], {"fra": FakeAdapter({"u1": used_bytes})})

    await service.sync_subscription("s1")

    assert sub.traffic_used_mib == 0
