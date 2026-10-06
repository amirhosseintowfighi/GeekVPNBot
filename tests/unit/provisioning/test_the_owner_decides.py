"""What a customer may change about their own service: auto-renewal, its name,
and who owns it."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from geekvpn.domain.provisioning import Subscription, SubscriptionRevoked
from geekvpn.domain.provisioning.errors import OrderValidationError

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def make_sub() -> Subscription:
    sub = Subscription.activate(
        "sub-1",
        user_id=1001,
        order_id="ord-1",
        plan_id="plan-30",
        remote_username="gv_1001_a1b2",
        now=NOW,
        duration_days=30,
    )
    sub.collect_events()
    return sub


def test_auto_renewal_is_off_until_the_owner_turns_it_on() -> None:
    sub = make_sub()
    assert sub.auto_renew is False

    sub.set_auto_renew(True)

    assert sub.auto_renew is True


def test_a_name_is_trimmed_and_an_empty_one_clears_it() -> None:
    sub = make_sub()

    sub.rename("  گوشی   مامان ")
    assert sub.display_name == "گوشی مامان"

    sub.rename("   ")
    assert sub.display_name is None


def test_a_name_too_long_for_a_button_is_refused() -> None:
    sub = make_sub()

    with pytest.raises(OrderValidationError):
        sub.rename("x" * 33)
    assert sub.display_name is None


def test_a_transfer_moves_the_owner_and_announces_it() -> None:
    sub = make_sub()

    sub.transfer_to(2002)

    assert sub.user_id == 2002
    [event] = sub.collect_events()
    assert event.name == "provisioning.subscription.transferred.v1"
    assert (event.from_user_id, event.to_user_id) == (1001, 2002)  # type: ignore[attr-defined]


def test_a_transfer_switches_auto_renewal_off() -> None:
    """It was the old owner's wallet that agreed to pay."""
    sub = make_sub()
    sub.set_auto_renew(True)

    sub.transfer_to(2002)

    assert sub.auto_renew is False


def test_a_service_cannot_be_given_to_its_own_owner() -> None:
    with pytest.raises(OrderValidationError):
        make_sub().transfer_to(1001)


def test_a_revoked_service_can_be_neither_renamed_nor_given_away() -> None:
    sub = make_sub()
    sub.revoke(reason_fa="تقلب", at=NOW)

    with pytest.raises(SubscriptionRevoked):
        sub.transfer_to(2002)
    with pytest.raises(SubscriptionRevoked):
        sub.rename("x")
