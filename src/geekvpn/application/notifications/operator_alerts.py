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

import enum
from collections.abc import Callable, Sequence
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
RECEIPT_ALERT_NO_IMAGE_FA = "برای این پرداخت تصویری ثبت نشده."
TICKET_OPENED_FA = (
    "🎫 <b>تیکت تازه</b> <code>{reference}</code>\n\n"
    "کاربر: <code>{user_id}</code>\n"
    "موضوع: {subject}\n\n"
    "{body}"
)
TICKET_REPLIED_FA = "💬 <b>پاسخ کاربر به تیکت</b>\n\nکاربر: <code>{user_id}</code>\n\n{body}"
TICKET_OPEN_LABEL_FA = "📂 باز کردن تیکت"
TOPUP_REPORT_FA = (
    "💳 <b>شارژ کیف پول</b>\n\n"
    "کاربر: <code>{user_id}</code>\n"
    "مبلغ: <b>{amount:,}</b> تومان\n"
    "موجودی جدید: {balance:,} تومان\n"
    "فاکتور: <code>{reference}</code>"
)
TRANSFER_REPORT_FA = (
    "🔁 <b>انتقال موجودی</b>\n\n"
    "از: <code>{from_user}</code>\n"
    "به: <code>{to_user}</code>\n"
    "مبلغ: <b>{amount:,}</b> تومان"
)


class AlertKind(enum.StrEnum):
    """Which stream an operator alert belongs to, and so which chat gets it."""

    RECEIPT = "receipt"
    PAYMENT = "payment"
    TICKET = "ticket"
    REPORT = "report"
    #: Services that ended or were deleted.
    SERVICE = "service"
    #: Free trials handed out.
    TRIAL = "trial"


class OperatorReports:
    """Sends an operator alert to the chat configured for its kind.

    A kind with no chat configured goes to every linked admin privately,
    which is exactly what every alert did before groups existed - so a shop
    that never sets a group sees no change.
    """

    def __init__(
        self,
        *,
        sender: OperatorSender,
        directory: OperatorDirectory,
        route: Callable[[AlertKind], int],
    ) -> None:
        self._sender = sender
        self._directory = directory
        self._route = route

    def chats(self, kind: AlertKind) -> list[int]:
        try:
            chat = self._route(kind)
        except Exception:
            # A settings read failing must not also cost the alert.
            logger.exception("alerts.route_failed", kind=kind.value)
            chat = 0
        if chat:
            return [chat]
        return list(self._directory.operator_chat_ids())

    def send(
        self, kind: AlertKind, text: str, buttons: Sequence[tuple[str, str]] = ()
    ) -> None:
        """Never raises: an alert is never worth rolling back what it reports."""
        for chat_id in self.chats(kind):
            try:
                self._sender.send_text(chat_id=chat_id, text=text, buttons=buttons)
            except Exception:
                logger.exception("alerts.operator_send_failed", chat_id=chat_id, kind=kind.value)

    def on_ticket_opened(self, event: Any) -> None:
        """Until now nothing told anybody a ticket arrived."""
        self.send(
            AlertKind.TICKET,
            TICKET_OPENED_FA.format(
                reference=event.reference,
                user_id=event.user_id,
                subject=_escape(event.subject_fa),
                body=_escape(_clip(event.first_message_fa)),
            ),
            buttons=[(TICKET_OPEN_LABEL_FA, f"adm:ticket:{event.ticket_id}")],
        )

    def on_wallet_credited(self, event: Any) -> None:
        """A settled top-up, whichever way it settled.

        The receipt alert covers a card payment while it waits; a gateway
        top-up never waits, so without this nobody heard of it at all.
        """
        if str(getattr(event, "kind", "")) != "topup":
            return
        self.send(
            AlertKind.PAYMENT,
            TOPUP_REPORT_FA.format(
                user_id=event.user_id,
                amount=event.amount,
                balance=event.balance_after,
                reference=event.reference or "—",
            ),
        )

    def on_ticket_replied(self, event: Any) -> None:
        # Only the customer's side. An operator's own reply echoing back to the
        # group would be noise, and a note is not a message.
        if str(getattr(event, "kind", "")) != "customer":
            return
        self.send(
            AlertKind.TICKET,
            TICKET_REPLIED_FA.format(user_id=event.user_id, body=_escape(_clip(event.body_fa))),
            buttons=[(TICKET_OPEN_LABEL_FA, f"adm:ticket:{event.ticket_id}")],
        )


def _clip(text: str, limit: int = 600) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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


class DeliveryNotifications:
    """Tells the customer their service is ready, and hands them the link."""

    def __init__(self, *, engine: Any) -> None:
        self._engine = engine

    def on_subscription_activated(self, event: Any, link: str | None) -> Any:
        """The link is passed in, never looked up.

        It was read back by id from a second session, and that read always
        found nothing: this runs inside provisioning, before the transaction
        that created the subscription has committed, so another connection
        cannot see the row yet. Every delivery therefore announced itself
        without the one thing the customer needed - and the row in the database
        had the link in it the whole time.

        A delivery with no link still gets the announcement: the account does
        exist, "my services" will show it, and silence is worse than an
        incomplete message.
        """

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
        #: Where a receipt goes. Without it, every linked admin privately.
        reports: OperatorReports | None = None,
    ) -> None:
        self._reports = reports
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
        payment = self._payments.get(event.payment_id)
        if payment is None:
            return

        if self._reports is not None:
            # Card receipts and everything else apart: on a busy day the crypto
            # proofs were lost in a scroll of card photos.
            is_card = str(getattr(payment, "method", "")) == "card"
            operators = self._reports.chats(AlertKind.RECEIPT if is_card else AlertKind.PAYMENT)
        else:
            operators = list(self._directory.operator_chat_ids())
        if not operators:
            logger.info("alerts.no_operators", payment_id=event.payment_id)
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
    "AlertKind",
    "DeliveryNotifications",
    "OperatorDirectory",
    "OperatorReports",
    "OperatorSender",
    "ReceiptAlerts",
    "rendered",
]
