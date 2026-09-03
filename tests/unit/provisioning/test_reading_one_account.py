"""Reading one subscription's usage asks the panel for that account.

It used to call `bulk_usage`, which lists the panel's first page of users and
picks ours out of it. When the account was not on that page the reading came
back empty, `sync_subscription` returned the row untouched, and the endpoint
reported success - so the operator pressed "به‌روزرسانی مصرف", was told the
usage had been read from the panel, and the figure stayed nine days stale.

That is the worst shape a failure can take: it says it worked.

`get_account` is one request for the account by name and cannot miss it. A
panel that genuinely does not have the account raises `AccountNotFound`, which
is a `PanelError`, so the endpoint reports that instead of success.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.application.provisioning.usage_sync import UsageSyncService
from geekvpn.domain.panels.enums import AccountState
from geekvpn.domain.panels.errors import AccountNotFound
from geekvpn.domain.panels.values import (
    AccountUsage,
    PanelAccount,
    PanelAccountRef,
    TrafficQuota,
)
from geekvpn.domain.provisioning.subscription import Subscription

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 3, tzinfo=UTC)
GIB = 1024 * 1024 * 1024


class FixedClock:
    def now(self) -> datetime:
        return NOW


def _subscription() -> Subscription:
    return Subscription(
        "sub-1",
        user_id=1,
        order_id="o1",
        plan_id="p1",
        started_at=NOW - timedelta(days=9),
        expires_at=NOW + timedelta(days=20),
        remote_username="gv140500011",
        node_id="n1",
        traffic_limit_mib=20 * 1024,
    )


class FakeSubscriptions:
    def __init__(self, subscription: Subscription) -> None:
        self.items = {subscription.id: subscription}

    async def get(self, subscription_id: str):
        return self.items.get(subscription_id)

    async def update(self, subscription: Subscription) -> None:
        self.items[subscription.id] = subscription


class FakeNodes:
    async def get(self, node_id: str):
        return type("N", (), {"id": node_id})()


class OnlyKnowsByName:
    """Bulk never returns this account; asking for it by name does.

    Exactly the panel this broke on: more users than one page, and ours not on
    the first one.
    """

    def __init__(self) -> None:
        self.bulk_calls = 0
        self.get_calls = 0

    async def bulk_usage(self, refs):
        self.bulk_calls += 1
        return {}

    async def get_account(self, ref: PanelAccountRef) -> PanelAccount:
        self.get_calls += 1
        return PanelAccount(
            ref=ref,
            state=AccountState.ACTIVE,
            usage=AccountUsage(
                used_bytes=3 * GIB + 450 * 1024 * 1024,
                measured_at=NOW,
                quota=TrafficQuota(20 * GIB),
                online_at=NOW - timedelta(hours=2),
            ),
        )


class KnowsNothing:
    async def bulk_usage(self, refs):
        return {}

    async def get_account(self, ref: PanelAccountRef) -> PanelAccount:
        raise AccountNotFound(panel="pasarguard", username=ref.username)


class FakePanels:
    def __init__(self, adapter) -> None:
        self._adapter = adapter

    async def for_node(self, node):
        return self._adapter


def _service(adapter, subscriptions: FakeSubscriptions) -> UsageSyncService:
    return UsageSyncService(
        subscriptions=subscriptions,
        nodes=FakeNodes(),
        panels=FakePanels(adapter),
        clock=FixedClock(),
    )


def test_the_reading_arrives_even_when_bulk_would_have_missed_it():
    """The bug, end to end."""
    subscriptions = FakeSubscriptions(_subscription())
    adapter = OnlyKnowsByName()

    updated = asyncio.run(_service(adapter, subscriptions).sync_subscription("sub-1"))

    assert updated is not None
    assert updated.traffic_used_mib == 3 * 1024 + 450


def test_it_does_not_page_through_the_panel_to_find_one_account():
    subscriptions = FakeSubscriptions(_subscription())
    adapter = OnlyKnowsByName()

    asyncio.run(_service(adapter, subscriptions).sync_subscription("sub-1"))

    assert adapter.bulk_calls == 0
    assert adapter.get_calls == 1


def test_the_sync_timestamp_actually_moves():
    """`last_synced_at` staying put behind a success message is what made this
    invisible for days."""
    subscriptions = FakeSubscriptions(_subscription())

    updated = asyncio.run(_service(OnlyKnowsByName(), subscriptions).sync_subscription("sub-1"))

    assert updated is not None
    assert updated.last_synced_at == NOW


def test_the_last_connection_comes_across_too():
    subscriptions = FakeSubscriptions(_subscription())

    updated = asyncio.run(_service(OnlyKnowsByName(), subscriptions).sync_subscription("sub-1"))

    assert updated is not None
    assert updated.last_connected_at == NOW - timedelta(hours=2)


def test_an_account_the_panel_does_not_have_is_not_reported_as_a_success():
    """It raises, and `AccountNotFound` is a `PanelError` - which the endpoint
    turns into "the panel said no" rather than "usage read"."""
    subscriptions = FakeSubscriptions(_subscription())

    with pytest.raises(AccountNotFound):
        asyncio.run(_service(KnowsNothing(), subscriptions).sync_subscription("sub-1"))


def test_a_subscription_never_provisioned_is_still_nothing_to_ask_about():
    """No panel account means no reading, and that is not a failure."""
    orphan = Subscription(
        str(uuid.uuid4()),
        user_id=1,
        order_id="o2",
        plan_id="p1",
        started_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=20),
        remote_username="",
        node_id=None,
    )
    subscriptions = FakeSubscriptions(orphan)

    assert asyncio.run(_service(OnlyKnowsByName(), subscriptions).sync_subscription(orphan.id)) is None
