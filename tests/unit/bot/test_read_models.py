"""Read-model behaviour.

Small properties, but they decide whether a customer sees a progress bar, a
renew button, or a credit sign - so they are worth pinning down.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from geekvpn.application.bot.read_models import (
    NotificationPreferences,
    SubscriptionCard,
    SubscriptionState,
    TransactionKind,
    WalletTransaction,
)


def card(**kwargs) -> SubscriptionCard:
    base = {
        "subscription_id": uuid.uuid4(),
        "plan_id": uuid.uuid4(),
        "product_name_fa": "\u062a\u0631\u0628\u0648",
        "plan_name_fa": "\u06cc\u06a9\u200c\u0645\u0627\u0647\u0647",
        "state": SubscriptionState.ACTIVE,
    }
    base.update(kwargs)
    return SubscriptionCard(**base)


class TestSubscriptionCard:
    def test_no_quota_means_unlimited(self) -> None:
        assert card(quota_gib=None).is_unlimited

    def test_unlimited_has_no_progress(self) -> None:
        """There is no bar to draw, so the fraction must be a flat zero."""
        assert card(quota_gib=None, used_gib=999.0).usage_fraction == 0.0

    def test_usage_fraction_is_proportional(self) -> None:
        assert card(quota_gib=100, used_gib=25.0).usage_fraction == pytest.approx(0.25)

    def test_overuse_clamps_to_one(self) -> None:
        """A 130% bar would render past the edge of the widget."""
        assert card(quota_gib=10, used_gib=13.0).usage_fraction == 1.0

    def test_remaining_never_negative(self) -> None:
        assert card(quota_gib=10, used_gib=13.0).remaining_gib == 0.0

    def test_remaining_is_none_when_unlimited(self) -> None:
        assert card(quota_gib=None).remaining_gib is None

    @pytest.mark.parametrize(
        "state",
        [
            SubscriptionState.ACTIVE,
            SubscriptionState.EXPIRING,
            SubscriptionState.EXPIRED,
            SubscriptionState.EXHAUSTED,
        ],
    )
    def test_renewable_states(self, state: SubscriptionState) -> None:
        assert card(state=state).is_renewable

    def test_suspended_is_not_renewable(self) -> None:
        """Taking money for a suspended line does not un-suspend it."""
        assert not card(state=SubscriptionState.SUSPENDED).is_renewable


class TestWalletTransaction:
    def _txn(self, kind: TransactionKind) -> WalletTransaction:
        return WalletTransaction(
            transaction_id=uuid.uuid4(),
            kind=kind,
            amount=1000,
            created_at=datetime.now(UTC),
        )

    @pytest.mark.parametrize(
        "kind",
        [
            TransactionKind.TOPUP,
            TransactionKind.CASHBACK,
            TransactionKind.REFERRAL,
            TransactionKind.REFUND,
        ],
    )
    def test_credits(self, kind: TransactionKind) -> None:
        assert self._txn(kind).is_credit

    def test_purchase_is_a_debit(self) -> None:
        assert not self._txn(TransactionKind.PURCHASE).is_credit


class TestNotificationPreferences:
    def test_toggle_flips_one_key(self) -> None:
        original = NotificationPreferences(expiry=True)
        assert original.with_toggled("expiry").expiry is False

    def test_toggle_leaves_others_alone(self) -> None:
        original = NotificationPreferences(expiry=True, traffic=True)
        assert original.with_toggled("expiry").traffic is True

    def test_toggle_is_immutable(self) -> None:
        original = NotificationPreferences(expiry=True)
        original.with_toggled("expiry")
        assert original.expiry is True

    def test_unknown_key_returns_self_by_identity(self) -> None:
        """This identity check is how a stale button from an old deploy is
        detected, so it must stay an identity and not an equal copy."""
        original = NotificationPreferences()
        assert original.with_toggled("nope") is original

    def test_round_trip_toggle(self) -> None:
        original = NotificationPreferences(news=False)
        assert original.with_toggled("news").with_toggled("news") == original

    def test_allows_defaults_true_for_unknown(self) -> None:
        assert NotificationPreferences().allows("unknown") is True
