"""Adopting an account that was sold outside the bot.

A customer buys through support, is sent a subscription link, and from then on
has no way to see their remaining traffic or expiry - the bot only knows about
what it sold. Pasting the link should find the account and record it as theirs.

The security-shaped tests here are the ones that matter. A subscription link is
a bearer token: anybody who has seen one, in a forwarded message or over an
operator's shoulder, must not be able to take somebody else's service with it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.application.provisioning.claim_service import ClaimOutcome, ClaimService
from geekvpn.domain.panels.enums import AccountState
from geekvpn.domain.panels.errors import PanelUnreachable
from geekvpn.domain.panels.values import (
    AccountUsage,
    PanelAccount,
    PanelAccountRef,
    TrafficQuota,
)
from geekvpn.domain.provisioning.enums import SubscriptionState
from geekvpn.domain.provisioning.subscription import Subscription

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 3, tzinfo=UTC)
GIB = 1024 * 1024 * 1024
LINK = "https://panel.example.com/sub/abc123token"


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeSubscriptions:
    def __init__(self, existing: list[Subscription] | None = None) -> None:
        self.items = {s.id: s for s in (existing or [])}
        self.added: list[Subscription] = []

    async def search(self, *, node_id=None, **_kw):
        found = [s for s in self.items.values() if node_id in (None, s.node_id)]
        return found, len(found)

    async def add(self, subscription: Subscription) -> None:
        self.added.append(subscription)
        self.items[subscription.id] = subscription


class FakeNode:
    def __init__(self, node_id: str) -> None:
        self.id = node_id


class FakeNodes:
    def __init__(self, ids: list[str]) -> None:
        self._ids = ids

    async def list_sellable(self):
        return [FakeNode(n) for n in self._ids]


def _account(username: str = "ali", *, expires_at: datetime | None = None) -> PanelAccount:
    return PanelAccount(
        ref=PanelAccountRef(panel_id=__import__("uuid").uuid4(), username=username),
        state=AccountState.ACTIVE,
        usage=AccountUsage(
            used_bytes=3 * GIB,
            measured_at=NOW,
            quota=TrafficQuota(50 * GIB),
        ),
        expires_at=expires_at if expires_at is not None else NOW + timedelta(days=20),
        subscription_url=LINK,
    )


class FakeAdapter:
    def __init__(self, *, account: PanelAccount | None, raises: bool = False) -> None:
        self._account = account
        self._raises = raises

    async def find_by_subscription(self, url: str) -> PanelAccount | None:
        if self._raises:
            raise PanelUnreachable(panel="marzban")
        return self._account


class FakePanels:
    def __init__(self, by_node: dict[str, FakeAdapter]) -> None:
        self._by_node = by_node

    async def for_node(self, node):
        return self._by_node[node.id]


def _service(
    *, by_node: dict[str, FakeAdapter], subscriptions: FakeSubscriptions | None = None
) -> tuple[ClaimService, FakeSubscriptions]:
    subs = subscriptions or FakeSubscriptions()
    service = ClaimService(
        subscriptions=subs,
        nodes=FakeNodes(list(by_node)),
        panels=FakePanels(by_node),
        clock=FixedClock(),
    )
    return service, subs


def test_a_real_link_becomes_a_service_the_customer_can_manage():
    service, subs = _service(by_node={"n1": FakeAdapter(account=_account())})

    result = asyncio.run(service.claim(url=LINK, user_id=99))

    assert result.outcome is ClaimOutcome.CLAIMED
    assert len(subs.added) == 1
    assert subs.added[0].user_id == 99
    assert subs.added[0].node_id == "n1"


def test_the_panel_decides_the_terms_not_the_customer():
    """Usage and quota are read back from the account, so pasting a link
    cannot conjure a service with better terms than the one it names."""
    service, subs = _service(by_node={"n1": FakeAdapter(account=_account())})

    asyncio.run(service.claim(url=LINK, user_id=99))

    claimed = subs.added[0]
    assert claimed.traffic_limit_mib == 50 * 1024
    assert claimed.traffic_used_mib == 3 * 1024


def test_a_claimed_service_has_no_order_behind_it():
    """Nobody bought it here. Synthesising an order would write a sale that
    never happened into the revenue figures."""
    service, subs = _service(by_node={"n1": FakeAdapter(account=_account())})

    asyncio.run(service.claim(url=LINK, user_id=99))

    assert subs.added[0].order_id is None
    assert subs.added[0].plan_id is None


def test_somebody_elses_service_cannot_be_taken_with_their_link():
    """The one that matters. A link is a bearer token."""
    mine = Subscription(
        "existing",
        user_id=1,
        order_id="o1",
        plan_id="p1",
        started_at=NOW - timedelta(days=5),
        expires_at=NOW + timedelta(days=20),
        remote_username="ali",
        node_id="n1",
    )
    service, subs = _service(
        by_node={"n1": FakeAdapter(account=_account("ali"))},
        subscriptions=FakeSubscriptions([mine]),
    )

    result = asyncio.run(service.claim(url=LINK, user_id=999))

    assert result.outcome is ClaimOutcome.ALREADY_CLAIMED
    assert subs.added == []
    assert subs.items["existing"].user_id == 1


def test_a_link_nobody_recognises_is_refused():
    service, subs = _service(by_node={"n1": FakeAdapter(account=None)})

    result = asyncio.run(service.claim(url=LINK, user_id=99))

    assert result.outcome is ClaimOutcome.NOT_FOUND
    assert subs.added == []


def test_every_panel_being_down_is_not_the_same_as_not_found():
    """Telling somebody holding a working link that their service does not
    exist, because a panel happened to be down, is the one wrong answer."""
    service, _ = _service(by_node={"n1": FakeAdapter(account=None, raises=True)})

    result = asyncio.run(service.claim(url=LINK, user_id=99))

    assert result.outcome is ClaimOutcome.PANEL_UNREACHABLE


def test_one_dead_panel_does_not_hide_an_account_on_another():
    service, subs = _service(
        by_node={
            "dead": FakeAdapter(account=None, raises=True),
            "alive": FakeAdapter(account=_account()),
        }
    )

    result = asyncio.run(service.claim(url=LINK, user_id=99))

    assert result.outcome is ClaimOutcome.CLAIMED
    assert subs.added[0].node_id == "alive"


def test_an_already_lapsed_account_is_not_recorded_as_active():
    """Otherwise the first thing the customer sees is a working service that
    will not connect."""
    expired = _account(expires_at=NOW - timedelta(days=2))
    service, subs = _service(by_node={"n1": FakeAdapter(account=expired)})

    asyncio.run(service.claim(url=LINK, user_id=99))

    assert subs.added[0].state is SubscriptionState.EXPIRED


def test_an_empty_message_is_not_a_search():
    service, subs = _service(by_node={"n1": FakeAdapter(account=_account())})

    result = asyncio.run(service.claim(url="   ", user_id=99))

    assert result.outcome is ClaimOutcome.NOT_FOUND
    assert subs.added == []
