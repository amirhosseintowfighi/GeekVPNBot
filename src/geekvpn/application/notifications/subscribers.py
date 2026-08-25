"""Event-driven notifications: wallet, purchases, support.

The payment system already emits precise events; this module is the only place
that turns them into customer-facing Persian. Nothing in ``application.payments``
imports the engine, which is what keeps a Telegram outage from being able to
roll back a payment.

All of these are transactional, so they are CRITICAL: unmutable and exempt
from quiet hours. Someone whose payment was rejected at 2am wants to know at
2am, because their service is not working.

The one exception is ``referral.reward``, which is PROMOS -- pleasant news,
not urgent news.
"""

from __future__ import annotations

from typing import Any

from geekvpn.application.notifications.engine import DispatchResult, NotificationEngine
from geekvpn.domain.notifications.enums import NotificationChannel
from geekvpn.domain.payments.events import (
    PaymentApproved,
    PaymentRefunded,
    PaymentRejected,
    WalletCredited,
    WalletDebited,
)

# Wallet movements caused by a purchase are already covered by the purchase
# message. Announcing both would tell the customer twice that they just paid.
_SILENT_DEBIT_KINDS = frozenset({"purchase"})


class WalletNotifications:
    """Money in, money out."""

    def __init__(self, *, engine: NotificationEngine) -> None:
        self._engine = engine

    def on_wallet_credited(self, event: WalletCredited) -> DispatchResult | None:
        """Route referral rewards to their own friendlier copy."""
        if event.kind == "referral_reward":
            return self._engine.notify(
                user_id=event.user_id,
                template_key="referral.reward",
                fields={"amount": event.amount},
                source="wallet.credited",
            )
        return self._engine.notify(
            user_id=event.user_id,
            template_key="wallet.credited",
            fields={"amount": event.amount, "balance": event.balance_after},
            source="wallet.credited",
        )

    def on_wallet_debited(self, event: WalletDebited) -> DispatchResult | None:
        if event.kind in _SILENT_DEBIT_KINDS:
            return None
        return self._engine.notify(
            user_id=event.user_id,
            template_key="wallet.debited",
            fields={"amount": event.amount, "balance": event.balance_after},
            source="wallet.debited",
        )


class PurchaseNotifications:
    """Payment outcomes and successful provisioning.

    ``PaymentApproved`` carries no reference field, so the payment id is used
    as the tracking code the customer quotes to support.
    """

    def __init__(self, *, engine: NotificationEngine) -> None:
        self._engine = engine

    def on_payment_approved(self, event: PaymentApproved) -> DispatchResult:
        return self._engine.notify(
            user_id=event.user_id,
            template_key="payment.approved",
            fields={"amount": event.amount, "reference": event.payment_id},
            dedupe_key=f"payment.approved:{event.payment_id}",
            source="payment.approved",
        )

    def on_payment_rejected(self, event: PaymentRejected) -> DispatchResult:
        return self._engine.notify(
            user_id=event.user_id,
            template_key="payment.rejected",
            fields={"reference": event.payment_id, "reason": event.reason_fa},
            dedupe_key=f"payment.rejected:{event.payment_id}",
            source="payment.rejected",
        )

    def on_payment_refunded(self, event: PaymentRefunded) -> DispatchResult:
        return self._engine.notify(
            user_id=event.user_id,
            template_key="payment.refunded",
            fields={"amount": event.amount, "reference": event.payment_id},
            source="payment.refunded",
        )

    def on_service_provisioned(
        self,
        *,
        user_id: int,
        plan_name: str,
        days: int,
        volume_fa: str,
        subscription_id: str | None = None,
    ) -> DispatchResult:
        """Called after the panel actually created the account.

        Separate from ``payment.approved`` on purpose: approval means the money
        cleared, provisioning means the service exists. Telling the customer
        their VPN is ready before it is ready generates a support ticket.
        """
        return self._engine.notify(
            user_id=user_id,
            template_key="purchase.completed",
            fields={"plan": plan_name, "days": days, "volume": volume_fa},
            dedupe_key=(f"purchase.completed:{subscription_id}" if subscription_id else None),
            source="provisioning",
        )

    def on_service_renewed(
        self,
        *,
        user_id: int,
        plan_name: str,
        days: int,
        subscription_id: str | None = None,
    ) -> DispatchResult:
        return self._engine.notify(
            user_id=user_id,
            template_key="purchase.renewed",
            fields={"plan": plan_name, "days": days},
            dedupe_key=(f"purchase.renewed:{subscription_id}:{days}" if subscription_id else None),
            source="provisioning",
        )


class EngineSupportNotifier:
    """The real implementation of ``application.support.ports.SupportNotifier``.

    Until now that Protocol had only test fakes behind it. Customer-facing
    messages go through the engine; agent-facing ones go straight to Telegram,
    because an operator's alert must not be filtered by a customer preference
    or held for quiet hours -- staff notifications are a different product.
    """

    def __init__(
        self,
        *,
        engine: NotificationEngine,
        agent_chat_ids: tuple[int, ...] = (),
    ) -> None:
        self._engine = engine
        self._agent_chat_ids = agent_chat_ids

    def notify_customer_reply(self, ticket: Any, message_body_fa: str) -> None:
        """Send the answer, not a notice that one exists.

        `message_body_fa` was accepted and discarded - the customer was told
        their ticket had a reply and had to go and find it. Most of a support
        answer is three lines long, and the round trip to read them is where
        the conversation was being lost.
        """
        self._engine.notify(
            user_id=ticket.user_id,
            template_key="ticket.answered",
            fields={"reference": ticket.reference, "body": message_body_fa},
            source="support.reply",
        )

    def notify_customer_closed(self, ticket: Any) -> None:
        self._engine.notify(
            user_id=ticket.user_id,
            template_key="ticket.closed",
            fields={"reference": ticket.reference},
            source="support.closed",
        )

    def notify_agent_new_ticket(self, ticket: Any, *, assignee_id: int | None = None) -> None:
        self._notify_agents(ticket, assignee_id=assignee_id)

    def notify_agent_customer_replied(self, ticket: Any, message_body_fa: str) -> None:
        self._notify_agents(ticket)

    def _notify_agents(self, ticket: Any, *, assignee_id: int | None = None) -> None:
        targets: tuple[int, ...] = (
            (assignee_id,) if assignee_id is not None else self._agent_chat_ids
        )
        for agent_id in targets:
            self._engine.notify(
                user_id=agent_id,
                template_key="ticket.replied",
                fields={"reference": ticket.reference},
                channels=(NotificationChannel.TELEGRAM,),
                force=True,
                source="support.agent",
            )


def register(
    dispatch_table: dict[str, Any],
    *,
    wallet: WalletNotifications,
    purchases: PurchaseNotifications,
) -> dict[str, Any]:
    """Wire event names to handlers.

    Keyed by the event's wire name rather than its class so the outbox can
    route a decoded payload without importing the payment domain.
    """
    dispatch_table.update(
        {
            WalletCredited.name: wallet.on_wallet_credited,
            WalletDebited.name: wallet.on_wallet_debited,
            PaymentApproved.name: purchases.on_payment_approved,
            PaymentRejected.name: purchases.on_payment_rejected,
            PaymentRefunded.name: purchases.on_payment_refunded,
        }
    )
    return dispatch_table


__all__ = [
    "EngineSupportNotifier",
    "PurchaseNotifications",
    "WalletNotifications",
    "register",
]
