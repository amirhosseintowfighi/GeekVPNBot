"""Payment and wallet events becoming Persian messages."""

from __future__ import annotations

from geekvpn.application.notifications.subscribers import register
from geekvpn.domain.notifications.enums import NotificationChannel
from geekvpn.domain.payments.events import (
    PaymentApproved,
    PaymentRejected,
    WalletCredited,
    WalletDebited,
)
from tests.unit.notifications.fakes import ADMIN_ID, USER_ID
from tests.unit.notifications.world import World


def _approved(payment_id: str = "pay-1") -> PaymentApproved:
    return PaymentApproved(
        payment_id=payment_id,
        invoice_id="inv-1",
        user_id=USER_ID,
        method="card",
        amount=680_000,
        approved_by=ADMIN_ID,
    )


def test_a_top_up_is_announced_with_its_balance():
    w = World()
    w.wallet.on_wallet_credited(
        WalletCredited(
            user_id=USER_ID,
            amount=100_000,
            balance_after=250_000,
            kind="topup",
            reference="pay-1",
        )
    )
    message = w.only().message
    assert message.key == "wallet.credited"
    assert "\u06f2\u06f5\u06f0" in message.body_fa


def test_a_referral_reward_gets_its_own_copy():
    w = World()
    w.wallet.on_wallet_credited(
        WalletCredited(
            user_id=USER_ID,
            amount=50_000,
            balance_after=50_000,
            kind="referral_reward",
            reference="ref-1",
        )
    )
    assert w.only().message.key == "referral.reward"


def test_a_purchase_debit_is_silent():
    """The purchase message already told them; twice is spam."""
    w = World()
    result = w.wallet.on_wallet_debited(
        WalletDebited(
            user_id=USER_ID,
            amount=680_000,
            balance_after=0,
            kind="purchase",
            reference="pay-1",
        )
    )
    assert result is None
    assert w.stored() == []


def test_a_non_purchase_debit_is_announced():
    w = World()
    w.wallet.on_wallet_debited(
        WalletDebited(
            user_id=USER_ID,
            amount=20_000,
            balance_after=5_000,
            kind="adjustment",
            reference="adj-1",
        )
    )
    assert w.only().message.key == "wallet.debited"


def test_an_approved_payment_notifies_with_a_tracking_code():
    w = World()
    w.purchases.on_payment_approved(_approved())
    message = w.only().message
    assert message.key == "payment.approved"
    assert "pay-1" in message.body_fa


def test_the_same_approval_twice_notifies_once():
    """Outbox redelivery is normal; double-notifying is not."""
    w = World()
    w.purchases.on_payment_approved(_approved())
    w.purchases.on_payment_approved(_approved())
    assert len(w.stored()) == 1


def test_a_rejection_carries_the_persian_reason():
    w = World()
    reason = (
        "\u0631\u0633\u06cc\u062f \u0646\u0627\u062e\u0648\u0627\u0646\u0627 \u0628\u0648\u062f"
    )
    w.purchases.on_payment_rejected(
        PaymentRejected(
            payment_id="pay-2",
            user_id=USER_ID,
            reason_fa=reason,
            rejected_by=ADMIN_ID,
        )
    )
    assert reason in w.only().message.body_fa


def test_payment_outcomes_reach_a_fully_muted_customer():
    """Money messages are CRITICAL; there is no switch for them."""
    w = World()
    for key in ("expiry", "traffic", "promos"):
        w.mute(key)
    w.purchases.on_payment_approved(_approved())
    assert w.only().state_for(NotificationChannel.TELEGRAM) is not None
    assert w.telegram.calls != []


def test_provisioning_is_a_separate_message_from_approval():
    """Approved means the money cleared; completed means the VPN exists."""
    w = World()
    w.purchases.on_payment_approved(_approved())
    w.purchases.on_service_provisioned(
        user_id=USER_ID,
        plan_name="Geek Turbo",
        days=30,
        volume_fa="\u06f1\u06f0\u06f0 \u06af\u06cc\u06af\u0627\u0628\u0627\u06cc\u062a",
        subscription_id="sub-1",
    )
    keys = sorted(n.message.key for n in w.stored())
    assert keys == ["payment.approved", "purchase.completed"]


def test_provisioning_twice_for_one_subscription_notifies_once():
    w = World()
    for _ in range(2):
        w.purchases.on_service_provisioned(
            user_id=USER_ID,
            plan_name="Geek Turbo",
            days=30,
            volume_fa="\u0646\u0627\u0645\u062d\u062f\u0648\u062f",
            subscription_id="sub-1",
        )
    assert len(w.stored()) == 1


def test_a_renewal_uses_the_renewal_copy():
    w = World()
    w.purchases.on_service_renewed(
        user_id=USER_ID, plan_name="Geek Elite", days=90, subscription_id="sub-1"
    )
    message = w.only().message
    assert message.key == "purchase.renewed"
    assert "\u06f9\u06f0" in message.body_fa


def test_the_dispatch_table_is_keyed_by_wire_name():
    """The outbox routes decoded payloads without importing the domain."""
    w = World()
    table = register({}, wallet=w.wallet, purchases=w.purchases)
    assert set(table) == {
        "billing.wallet.credited.v1",
        "billing.wallet.debited.v1",
        "billing.payment.approved.v1",
        "billing.payment.rejected.v1",
        "billing.payment.refunded.v1",
    }


def test_routing_an_event_through_the_table_notifies():
    w = World()
    table = register({}, wallet=w.wallet, purchases=w.purchases)
    event = _approved("pay-9")
    table[PaymentApproved.name](event)
    assert w.only().message.key == "payment.approved"
