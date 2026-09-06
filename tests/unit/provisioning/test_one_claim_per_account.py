"""A subscription link can only be adopted once.

The check was a page: read a thousand subscriptions for the node, scan them in
Python. On a node holding more than that it answered "no" without having
looked, so the same link could be adopted again and again - by the customer who
already had it, or by anybody else who had seen it.

Two tests here are about the *shape* of the check rather than its answer, and
that is the point: a check that reads a page is right on small data and wrong
in production, which is exactly the failure that shipped.
"""

from __future__ import annotations

import asyncio
import uuid
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
from geekvpn.domain.provisioning.enums import SubscriptionState
from geekvpn.domain.provisioning.subscription import Subscription
from tests.unit.provisioning.test_claiming_an_existing_account import (
    FakeNode,
    FakeSubscriptions,
    FixedClock,
)
from tests.unit.provisioning.test_which_panel_the_link_came_from import (
    Nodes,
    Panels,
    RecordingAdapter,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 7, tzinfo=UTC)
GIB = 1024**3
API = "https://panel.example.com"
LINK = f"{API}/sub/tok"
USERNAME = "amir"


def _account() -> PanelAccount:
    return PanelAccount(
        ref=PanelAccountRef(panel_id=uuid.uuid4(), username=USERNAME),
        state=AccountState.ACTIVE,
        usage=AccountUsage(used_bytes=GIB, measured_at=NOW, quota=TrafficQuota(50 * GIB)),
        expires_at=NOW + timedelta(days=10),
        subscription_url=LINK,
    )


def _existing(user_id: int) -> Subscription:
    return Subscription(
        str(uuid.uuid4()),
        user_id=user_id,
        order_id=None,
        plan_id=None,
        started_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=10),
        remote_username=USERNAME,
        state=SubscriptionState.ACTIVE,
        node_id="n1",
    )


def _service(existing: list[Subscription] | None = None):
    subs = FakeSubscriptions(existing or [])
    service = ClaimService(
        subscriptions=subs,
        nodes=Nodes([FakeNode("n1", base_url=API)]),
        panels=Panels({"n1": RecordingAdapter([], "n1", _account())}),
        clock=FixedClock(),
    )
    return service, subs


def test_the_same_link_twice_is_refused():
    service, subs = _service()

    first = asyncio.run(service.claim(url=LINK, user_id=7))
    second = asyncio.run(service.claim(url=LINK, user_id=7))

    assert first.outcome is ClaimOutcome.CLAIMED
    assert second.outcome is not ClaimOutcome.CLAIMED
    assert len(subs.added) == 1


def test_a_customer_pasting_their_own_link_again_is_told_it_is_theirs():
    """Not "this belongs to somebody else" - that sends a customer to support
    over a link they pasted twice, which is most of the times this happens."""
    service, _ = _service([_existing(user_id=7)])

    result = asyncio.run(service.claim(url=LINK, user_id=7))

    assert result.outcome is ClaimOutcome.ALREADY_YOURS


def test_somebody_elses_link_is_still_refused_as_taken():
    """The security case. A subscription link is a bearer token: anybody who
    has seen it once could otherwise take the service off its owner."""
    service, subs = _service([_existing(user_id=7)])

    result = asyncio.run(service.claim(url=LINK, user_id=99))

    assert result.outcome is ClaimOutcome.ALREADY_CLAIMED
    assert subs.added == []


def test_the_check_is_a_query_not_a_page():
    """The actual bug. `search(limit=1000)` answers "not claimed" for a node
    holding more than a thousand accounts, and does so without looking."""
    asked: list[tuple[str, str]] = []

    class Counting(FakeSubscriptions):
        async def search(self, **kwargs):  # pragma: no cover - must not be called
            raise AssertionError("the claim read a page to answer an existence question")

        async def owner_of_account(self, node_id: str, remote_username: str) -> int | None:
            asked.append((node_id, remote_username))
            return None

    subs = Counting()
    service = ClaimService(
        subscriptions=subs,
        nodes=Nodes([FakeNode("n1", base_url=API)]),
        panels=Panels({"n1": RecordingAdapter([], "n1", _account())}),
        clock=FixedClock(),
    )

    asyncio.run(service.claim(url=LINK, user_id=7))

    assert asked == [("n1", USERNAME)]


def test_the_database_enforces_it_too():
    """The application check cannot see a concurrent claim: two taps of the
    same button are two transactions, and both find nothing."""
    from geekvpn.infrastructure.persistence.models.provisioning import SubscriptionModel

    index = next(
        (
            item
            for item in SubscriptionModel.__table_args__
            if getattr(item, "name", "") == "ux_subscriptions_claimed_account"
        ),
        None,
    )

    assert index is not None
    assert index.unique
    assert [column.name for column in index.columns] == ["node_id", "remote_username"]
