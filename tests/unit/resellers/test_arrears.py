"""A reseller who owes money has their customers turned off.

This is the credit limit. There is no agreed ceiling and no settlement date -
there is a consequence, applied to a debt that already exists rather than to
the next purchase, and it gives the reseller exactly one thing to do about it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest

from geekvpn.application.resellers.arrears import ARREARS_REASON_FA, ArrearsEnforcer
from geekvpn.domain.provisioning.enums import SubscriptionState

pytestmark = pytest.mark.unit

RESELLER = uuid.uuid4()


@dataclass
class Sub:
    id: str
    state: SubscriptionState = SubscriptionState.ACTIVE
    suspend_reason_fa: str | None = None


@dataclass
class Subscriptions:
    rows: list[Sub] = field(default_factory=list)

    async def list_for_reseller(self, reseller_id: uuid.UUID) -> list[Sub]:
        return list(self.rows) if reseller_id == RESELLER else []


class Access:
    """Stands in for the panel, and records what it was asked to do."""

    def __init__(self, *, breaks: set[str] | None = None) -> None:
        self.suspended: list[str] = []
        self.resumed: list[str] = []
        self._breaks = breaks or set()

    async def suspend(self, subscription_id: str, *, reason_fa: str) -> None:
        if subscription_id in self._breaks:
            raise RuntimeError("panel unreachable")
        self.suspended.append(subscription_id)

    async def resume(self, subscription_id: str) -> None:
        if subscription_id in self._breaks:
            raise RuntimeError("panel unreachable")
        self.resumed.append(subscription_id)


def _enforcer(rows: list[Sub], *, breaks: set[str] | None = None):
    access = Access(breaks=breaks)
    return ArrearsEnforcer(subscriptions=Subscriptions(rows), access=access), access


async def test_going_into_arrears_suspends_every_active_customer():
    enforcer, access = _enforcer([Sub("a"), Sub("b")])

    outcome = await enforcer.apply(reseller_id=RESELLER, in_arrears=True)

    assert access.suspended == ["a", "b"]
    assert outcome.suspended == 2


async def test_paying_the_debt_brings_them_back():
    rows = [
        Sub("a", SubscriptionState.SUSPENDED, ARREARS_REASON_FA),
        Sub("b", SubscriptionState.SUSPENDED, ARREARS_REASON_FA),
    ]
    enforcer, access = _enforcer(rows)

    outcome = await enforcer.apply(reseller_id=RESELLER, in_arrears=False)

    assert access.resumed == ["a", "b"]
    assert outcome.resumed == 2


async def test_a_subscription_an_operator_suspended_is_left_alone():
    """The whole reason the reason is stored.

    Somebody banned for abuse must not come back because an unrelated balance
    was topped up - and without a stored reason nothing could tell the two
    suspensions apart after the fact.
    """
    rows = [Sub("banned", SubscriptionState.SUSPENDED, "سوءاستفاده")]
    enforcer, access = _enforcer(rows)

    await enforcer.apply(reseller_id=RESELLER, in_arrears=False)

    assert access.resumed == []


async def test_running_twice_does_nothing_the_second_time():
    """It runs after every balance change, and a wasted panel call per
    subscription per top-up adds up fast."""
    rows = [Sub("a", SubscriptionState.SUSPENDED, ARREARS_REASON_FA)]
    enforcer, access = _enforcer(rows)

    await enforcer.apply(reseller_id=RESELLER, in_arrears=True)

    assert access.suspended == []


async def test_an_expired_subscription_is_not_woken_up():
    """Only active ones are suspended and only suspended ones resumed. An
    expired or revoked service has a reason of its own to be off."""
    rows = [Sub("gone", SubscriptionState.EXPIRED)]
    enforcer, access = _enforcer(rows)

    await enforcer.apply(reseller_id=RESELLER, in_arrears=True)
    await enforcer.apply(reseller_id=RESELLER, in_arrears=False)

    assert access.suspended == []
    assert access.resumed == []


async def test_a_panel_that_is_down_does_not_stop_the_others():
    """Nor does it turn an operator's balance adjustment into an error. The
    next run picks the failure up, because the state it reads is the truth."""
    enforcer, access = _enforcer([Sub("a"), Sub("broken"), Sub("c")], breaks={"broken"})

    outcome = await enforcer.apply(reseller_id=RESELLER, in_arrears=True)

    assert access.suspended == ["a", "c"]
    assert outcome.failed == 1
    assert outcome.suspended == 2


async def test_another_resellers_customers_are_not_touched():
    """And neither are the platform's own, which carry no reseller at all."""
    enforcer, access = _enforcer([Sub("a")])

    await enforcer.apply(reseller_id=uuid.uuid4(), in_arrears=True)

    assert access.suspended == []
