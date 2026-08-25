"""What the bot tells operators, and what it tells a customer on delivery.

Two subscribers that were missing, both for the same reason: the events were
published and nothing listened.

`SubscriptionActivated` is the moment a customer's service exists. Until now
the bot said nothing - `on_service_provisioned` was written, and called by
nobody, so somebody paid and then sat looking at a chat that had gone quiet.

`ProofSubmitted` is the moment an operator has work to do. The panel showed it
in a queue nobody had open at one in the morning; the receipt now arrives in
Telegram, as the image, with the two buttons that decide it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

import structlog

from geekvpn.domain.notifications.enums import NotificationCategory
from geekvpn.domain.notifications.message import RenderedMessage

logger = structlog.stdlib.get_logger(__name__)


#: The alert's own Persian copy.
#:
#: Here rather than in `presentation/bot/ui`, which is where customer-facing
#: text belongs: `import-linter` forbids infrastructure from importing
#: presentation, and this alert is assembled in the synchronous scope. The
#: labels are passed in by the caller so the bot's own buttons and this
#: message cannot say two different words for the same decision.
RECEIPT_ALERT_FA = (
    "\U0001f9fe <b>رسید تازه</b>\n\n"
    "مبلغ: <b>{amount:,}</b> تومان\n"
    "کاربر: <code>{user_id}</code>\n"
    "کد پیگیری: <code>{reference}</code>"
)
APPROVE_LABEL_FA = "\u2705 تأیید"
REJECT_LABEL_FA = "\u274c رد"
RECEIPT_ALERT_NO_IMAGE_FA = "برای این پرداخت تصویری ثبت نشده است."


class OperatorSender(Protocol):
    """The slice of the Bot API an operator alert needs.

    Separate from `TelegramSender`, which sends a customer a rendered template.
    This one sends an image with decisions attached, and the two have no
    overlap beyond the word "send".
    """

    def send_photo(
        self,
        *,
        chat_id: int,
        file_id: str,
        caption: str,
        buttons: Sequence[tuple[str, str]],
    ) -> None:
        """`buttons` are (label, callback data) pairs - no aiogram types, so
        the engine stays testable without the bot installed."""
        ...

    def send_text(self, *, chat_id: int, text: str, buttons: Sequence[tuple[str, str]]) -> None:
        ...


class OperatorDirectory(Protocol):
    def operator_chat_ids(self) -> Sequence[int]:
        """Telegram ids of admins who can act on this, and no one else."""
        ...


class PaymentLookup(Protocol):
    def get(self, payment_id: str) -> Any: ...


class SubscriptionLinks(Protocol):
    def subscription_url(self, subscription_id: str) -> str | None: ...


class DeliveryNotifications:
    """Tells the customer their service is ready, and hands them the link."""

    def __init__(self, *, engine: Any, links: SubscriptionLinks) -> None:
        self._engine = engine
        self._links = links

    def on_subscription_activated(self, event: Any) -> Any:
        """The link matters more than the announcement.

        A "your service is ready" with no way to use it is a support ticket, so
        the subscription is read back for its URL and the message carries it.
        A subscription with no URL yet still gets the announcement - the
        customer can fetch the config from "my services" - because silence is
        worse than an incomplete message.
        """
        link = self._links.subscription_url(event.subscription_id)

        return self._engine.notify(
            user_id=event.user_id,
            template_key="purchase.delivered" if link else "purchase.delivered_no_link",
            fields={"link": link} if link else {},
            # One per subscription. A retry that re-publishes the event must not
            # send the customer a second copy of their own config.
            dedupe_key=f"purchase.delivered:{event.subscription_id}",
            source="provisioning",
        )


class ReceiptAlerts:
    """Puts a submitted receipt in front of whoever can decide it."""

    def __init__(
        self,
        *,
        sender: OperatorSender,
        directory: OperatorDirectory,
        payments: PaymentLookup,
        approve_label: str,
        reject_label: str,
        caption: str,
        no_image_caption: str,
    ) -> None:
        self._sender = sender
        self._directory = directory
        self._payments = payments
        self._approve_label = approve_label
        self._reject_label = reject_label
        self._caption = caption
        self._no_image_caption = no_image_caption

    def on_proof_submitted(self, event: Any) -> None:
        """Never raises into the publisher.

        This runs inside the transaction that accepted the customer's receipt.
        A Telegram outage must not roll that back - the receipt is safely
        stored and the review queue still has it, so a failure here costs an
        operator a notification, not a customer their proof.
        """
        operators = list(self._directory.operator_chat_ids())
        if not operators:
            logger.info("alerts.no_operators", payment_id=event.payment_id)
            return

        payment = self._payments.get(event.payment_id)
        if payment is None:
            return

        amount = getattr(getattr(payment, "amount", None), "amount", 0)
        caption = self._caption.format(
            amount=amount, user_id=event.user_id, reference=event.reference
        )
        buttons = [
            (self._approve_label, f"adm:approve:{event.payment_id}"),
            (self._reject_label, f"adm:reject:{event.payment_id}"),
        ]
        file_id = getattr(getattr(payment, "proof", None), "file_id", None)

        for chat_id in operators:
            try:
                if file_id:
                    self._sender.send_photo(
                        chat_id=chat_id, file_id=file_id, caption=caption, buttons=buttons
                    )
                else:
                    self._sender.send_text(
                        chat_id=chat_id,
                        text=f"{caption}\n\n{self._no_image_caption}",
                        buttons=buttons,
                    )
            except Exception:
                logger.exception("alerts.operator_send_failed", chat_id=chat_id)


def rendered(title_fa: str, body_fa: str) -> RenderedMessage:
    return RenderedMessage(
        key="operator.alert",
        category=NotificationCategory.CRITICAL,
        title_fa=title_fa,
        body_fa=body_fa,
    )


__all__ = [
    "APPROVE_LABEL_FA",
    "RECEIPT_ALERT_FA",
    "RECEIPT_ALERT_NO_IMAGE_FA",
    "REJECT_LABEL_FA",
    "DeliveryNotifications",
    "OperatorDirectory",
    "OperatorSender",
    "ReceiptAlerts",
    "rendered",
]
