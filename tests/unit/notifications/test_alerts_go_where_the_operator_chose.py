"""Each kind of operator alert goes to the chat the operator chose for it.

Every alert used to go to every admin's private chat. That meant a receipt
could only be decided by whoever happened to be awake and linked, crypto
proofs drowned in a scroll of card photos, and nobody was told about a new
ticket at all.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from geekvpn.application.notifications.operator_alerts import (
    AlertKind,
    OperatorReports,
    ReceiptAlerts,
)
from tests.unit.notifications.test_delivery_and_alerts import (
    SUBMITTED,
    Directory,
    Payments,
    Sender,
)

pytestmark = pytest.mark.unit

ADMINS = [111, 222]
RECEIPTS_GROUP = -100_1
PAYMENTS_GROUP = -100_2
TICKETS_GROUP = -100_3


def reports(sender: Sender, routes: dict[AlertKind, int]) -> OperatorReports:
    return OperatorReports(
        sender=sender, directory=Directory(ADMINS), route=lambda kind: routes.get(kind, 0)
    )


def test_with_no_group_set_every_admin_is_told_privately() -> None:
    sender = Sender()

    reports(sender, {}).send(AlertKind.REPORT, "hello")

    assert [t["chat_id"] for t in sender.texts] == ADMINS


def test_with_a_group_set_only_the_group_is_told() -> None:
    sender = Sender()

    reports(sender, {AlertKind.REPORT: -555}).send(AlertKind.REPORT, "hello")

    assert [t["chat_id"] for t in sender.texts] == [-555]


def receipt_alerts(sender: Sender, method: str, routes: dict[AlertKind, int]) -> ReceiptAlerts:
    paid = SimpleNamespace(
        method=method,
        amount=SimpleNamespace(amount=200_000),
        proof=SimpleNamespace(file_id="photo-1"),
    )
    return ReceiptAlerts(
        sender=sender,
        directory=Directory(ADMINS),
        payments=Payments(paid),
        approve_label="ok",
        reject_label="no",
        caption="{amount} {user_id} {reference}",
        no_image_caption="",
        reports=reports(sender, routes),
    )


def test_a_card_receipt_goes_to_the_receipts_group() -> None:
    sender = Sender()
    routes = {AlertKind.RECEIPT: RECEIPTS_GROUP, AlertKind.PAYMENT: PAYMENTS_GROUP}

    receipt_alerts(sender, "card", routes).on_proof_submitted(SUBMITTED)

    assert [p["chat_id"] for p in sender.photos] == [RECEIPTS_GROUP]


def test_a_crypto_proof_goes_to_the_other_payments_group() -> None:
    sender = Sender()
    routes = {AlertKind.RECEIPT: RECEIPTS_GROUP, AlertKind.PAYMENT: PAYMENTS_GROUP}

    receipt_alerts(sender, "crypto", routes).on_proof_submitted(SUBMITTED)

    assert [p["chat_id"] for p in sender.photos] == [PAYMENTS_GROUP]


def test_the_group_keeps_the_approve_buttons_any_admin_can_press() -> None:
    sender = Sender()

    receipt_alerts(sender, "card", {AlertKind.RECEIPT: RECEIPTS_GROUP}).on_proof_submitted(
        SUBMITTED
    )

    [photo] = sender.photos
    assert ("ok", "adm:approve:pay-1") in photo["buttons"]  # type: ignore[operator]


TICKET = SimpleNamespace(
    ticket_id="t-1",
    user_id=42,
    reference="TK-7",
    subject_fa="وصل نمی‌شم",
    first_message_fa="از دیشب <قطعه>",
)


def test_a_new_ticket_reaches_the_tickets_group_with_a_button_to_open_it() -> None:
    sender = Sender()

    reports(sender, {AlertKind.TICKET: TICKETS_GROUP}).on_ticket_opened(TICKET)

    [text] = sender.texts
    assert text["chat_id"] == TICKETS_GROUP
    assert "TK-7" in str(text["text"])
    assert "&lt;قطعه&gt;" in str(text["text"])
    assert text["buttons"] == [("📂 باز کردن تیکت", "adm:ticket:t-1")]


def test_only_the_customers_replies_are_announced() -> None:
    sender = Sender()
    alerts = reports(sender, {AlertKind.TICKET: TICKETS_GROUP})
    reply = {"ticket_id": "t-1", "user_id": 42, "body_fa": "هنوز نه"}

    alerts.on_ticket_replied(SimpleNamespace(kind="support", **reply))
    alerts.on_ticket_replied(SimpleNamespace(kind="note", **reply))
    alerts.on_ticket_replied(SimpleNamespace(kind="customer", **reply))

    assert len(sender.texts) == 1


def test_a_broken_settings_read_still_delivers_the_alert() -> None:
    sender = Sender()

    def broken(kind: AlertKind) -> int:
        raise RuntimeError("db down")

    OperatorReports(sender=sender, directory=Directory(ADMINS), route=broken).send(
        AlertKind.REPORT, "x"
    )

    assert [t["chat_id"] for t in sender.texts] == ADMINS


def test_the_cleanup_job_is_on_the_workers_table() -> None:
    from types import SimpleNamespace

    from geekvpn.entrypoints.worker import Worker

    worker = Worker(SimpleNamespace())  # type: ignore[arg-type]

    assert "cleanup" in {name for name, _, _ in worker._periodic}
