"""Telling two panels apart when both hold an account with the same name.

The operator runs several panels, and each has a customer called `amir`. A
username identifies nothing across them; the token does, and so does the host
the link was served from. This checks the host is used - to ask the right panel
first, and to hand back a link on the host that actually serves it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.application.provisioning.claim_service import ClaimOutcome, ClaimService
from geekvpn.domain.panels.enums import AccountState
from geekvpn.domain.panels.values import (
    AccountUsage,
    PanelAccount,
    PanelAccountRef,
    TrafficQuota,
)
from tests.unit.provisioning.test_claiming_an_existing_account import (
    FakeNode,
    FakeSubscriptions,
    FixedClock,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 7, tzinfo=UTC)
GIB = 1024**3
TOKEN = "djMsMSwxNzg4NDQxMjYw"

#: The API host, and the host the customer's link is on. They differ.
API_A, SUB_A = "https://panel.doping.games:8443", "https://panel2.hostcheap.top"
API_B = "https://multi.hostcheap.top:8443"

PASTED = f"{SUB_A}/sub/{TOKEN}"


def _account(username: str, url: str) -> PanelAccount:
    return PanelAccount(
        ref=PanelAccountRef(panel_id=__import__("uuid").uuid4(), username=username),
        state=AccountState.ACTIVE,
        usage=AccountUsage(used_bytes=GIB, measured_at=NOW, quota=TrafficQuota(50 * GIB)),
        expires_at=NOW + timedelta(days=10),
        subscription_url=url,
    )


class RecordingAdapter:
    """Answers only for its own token, and remembers it was asked."""

    def __init__(self, order: list[str], node_id: str, account: PanelAccount | None) -> None:
        self._order = order
        self._node_id = node_id
        self._account = account

    async def find_by_subscription(self, url: str) -> PanelAccount | None:
        self._order.append(self._node_id)
        return self._account


class Nodes:
    def __init__(self, nodes: list[FakeNode]) -> None:
        self._nodes = nodes

    async def list_sellable(self):
        return []

    async def list_every(self):
        return list(self._nodes)


class Panels:
    def __init__(self, by_node: dict[str, RecordingAdapter]) -> None:
        self._by_node = by_node

    async def for_node(self, node):
        return self._by_node[node.id]


def _setup(*, both_answer: bool):
    """Two panels, each holding an account called `amir`."""
    order: list[str] = []
    nodes = [
        # Deliberately first, so "asked first" cannot pass by accident.
        FakeNode("other", base_url=API_B),
        FakeNode("ours", base_url=API_A, subscription_base_url=SUB_A),
    ]
    adapters = {
        "other": RecordingAdapter(
            order, "other", _account("amir", f"{API_B}/sub/{TOKEN}") if both_answer else None
        ),
        "ours": RecordingAdapter(order, "ours", _account("amir", f"{API_A}/sub/{TOKEN}")),
    }
    subs = FakeSubscriptions()
    service = ClaimService(
        subscriptions=subs,
        nodes=Nodes(nodes),
        panels=Panels(adapters),
        clock=FixedClock(),
    )
    return service, subs, order


def test_the_panel_the_link_names_is_asked_first():
    """With `amir` on both, whichever panel is asked first wins - so it has to
    be the one the link actually came from, not the one that sorts first."""
    service, _, order = _setup(both_answer=True)

    asyncio.run(service.claim(url=PASTED, user_id=1))

    assert order[0] == "ours"


def test_the_right_account_is_the_one_recorded():
    service, subs, _ = _setup(both_answer=True)

    result = asyncio.run(service.claim(url=PASTED, user_id=1))

    assert result.outcome is ClaimOutcome.CLAIMED
    assert subs.added[0].node_id == "ours"


def test_the_other_panels_are_still_asked():
    """The host is a hint, not a filter. A link on a host we do not have
    recorded must still be found on whichever panel actually minted it."""
    order: list[str] = []
    nodes = [FakeNode("other", base_url=API_B), FakeNode("ours", base_url=API_A)]
    adapters = {
        "other": RecordingAdapter(order, "other", None),
        "ours": RecordingAdapter(order, "ours", _account("amir", f"{API_A}/sub/{TOKEN}")),
    }
    subs = FakeSubscriptions()
    service = ClaimService(
        subscriptions=subs, nodes=Nodes(nodes), panels=Panels(adapters), clock=FixedClock()
    )

    result = asyncio.run(service.claim(url="https://unknown.example.com/sub/x", user_id=1))

    assert order == ["other", "ours"]
    assert result.outcome is ClaimOutcome.CLAIMED


def test_the_stored_link_is_the_one_the_customer_can_open():
    """The panel answers with its API host. Storing that hands the customer a
    link to a host that does not serve them, and it looks like a dead service.
    """
    service, subs, _ = _setup(both_answer=False)

    asyncio.run(service.claim(url=PASTED, user_id=1))

    assert subs.added[0].subscription_url == f"{SUB_A}/sub/{TOKEN}"


def test_a_node_with_no_separate_host_keeps_the_panels_answer():
    order: list[str] = []
    nodes = [FakeNode("plain", base_url=API_B)]
    adapters = {"plain": RecordingAdapter(order, "plain", _account("amir", f"{API_B}/sub/{TOKEN}"))}
    subs = FakeSubscriptions()
    service = ClaimService(
        subscriptions=subs, nodes=Nodes(nodes), panels=Panels(adapters), clock=FixedClock()
    )

    asyncio.run(service.claim(url=f"{API_B}/sub/{TOKEN}", user_id=1))

    assert subs.added[0].subscription_url == f"{API_B}/sub/{TOKEN}"
