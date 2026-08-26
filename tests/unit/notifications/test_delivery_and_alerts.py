"""The two messages nobody was sending.

`on_service_provisioned` was written and subscribed by nothing, so a customer
paid and then watched the chat go quiet. `ProofSubmitted` was published and
heard by nothing, so a receipt sat in a queue nobody had open.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from geekvpn.application.notifications.operator_alerts import (
    APPROVE_LABEL_FA,
    RECEIPT_ALERT_FA,
    DeliveryNotifications,
    ReceiptAlerts,
)

pytestmark = pytest.mark.unit


class Engine:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def notify(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return "sent"


class Sender:
    def __init__(self, *, breaks: bool = False) -> None:
        self.photos: list[dict[str, object]] = []
        self.texts: list[dict[str, object]] = []
        self._breaks = breaks

    def send_photo(self, **kwargs: object) -> None:
        if self._breaks:
            raise RuntimeError("telegram is down")
        self.photos.append(kwargs)

    def send_text(self, **kwargs: object) -> None:
        if self._breaks:
            raise RuntimeError("telegram is down")
        self.texts.append(kwargs)


class Directory:
    def __init__(self, ids: list[int]) -> None:
        self._ids = ids

    def operator_chat_ids(self) -> list[int]:
        return self._ids


class Payments:
    def __init__(self, payment: object | None) -> None:
        self._payment = payment

    def get(self, payment_id: str) -> object | None:
        return self._payment


ACTIVATED = SimpleNamespace(subscription_id="sub-1", user_id=87791922)
SUBMITTED = SimpleNamespace(payment_id="pay-1", user_id=87791922, reference="1405-000009")


def payment(file_id: str | None = "photo-1") -> SimpleNamespace:
    return SimpleNamespace(
        amount=SimpleNamespace(amount=200_000),
        proof=SimpleNamespace(file_id=file_id),
    )


# -- delivery --------------------------------------------------------------


def test_the_customer_is_sent_their_link() -> None:
    engine = Engine()
    DeliveryNotifications(engine=engine).on_subscription_activated(ACTIVATED, "https://sub/abc")

    assert engine.calls[0]["template_key"] == "purchase.delivered"
    assert engine.calls[0]["fields"] == {"link": "https://sub/abc"}


def test_the_link_is_handed_over_rather_than_looked_up() -> None:
    """It used to be read back by id, from a second session, inside the
    transaction that had just created the row - so the read always found
    nothing and every delivery went out without the one thing the customer
    needed. The notifier now has no way to look anything up."""
    import inspect

    signature = inspect.signature(DeliveryNotifications.__init__)

    assert set(signature.parameters) == {"self", "engine"}


def test_a_subscription_with_no_link_yet_is_still_announced() -> None:
    """Silence is worse than an incomplete message: the account exists."""
    engine = Engine()
    DeliveryNotifications(engine=engine).on_subscription_activated(ACTIVATED, None)

    assert engine.calls[0]["template_key"] == "purchase.delivered_no_link"


def test_it_is_deduped_per_subscription() -> None:
    """A retry that re-publishes must not send a second copy of the config."""
    engine = Engine()
    DeliveryNotifications(engine=engine).on_subscription_activated(ACTIVATED, "x")

    assert engine.calls[0]["dedupe_key"] == "purchase.delivered:sub-1"


# -- the receipt alert -----------------------------------------------------


def build(sender: Sender, *, operators: list[int], file_id: str | None = "photo-1") -> ReceiptAlerts:
    return ReceiptAlerts(
        sender=sender,
        directory=Directory(operators),
        payments=Payments(payment(file_id)),
        approve_label=APPROVE_LABEL_FA,
        reject_label="رد",
        caption=RECEIPT_ALERT_FA,
        no_image_caption="بدون تصویر",
    )


def test_every_operator_gets_the_image() -> None:
    sender = Sender()
    build(sender, operators=[1, 2]).on_proof_submitted(SUBMITTED)

    assert [photo["chat_id"] for photo in sender.photos] == [1, 2]
    assert sender.photos[0]["file_id"] == "photo-1"


def test_the_caption_carries_what_a_decision_needs() -> None:
    sender = Sender()
    build(sender, operators=[1]).on_proof_submitted(SUBMITTED)

    caption = str(sender.photos[0]["caption"])
    assert "200,000" in caption
    assert "87791922" in caption
    assert "1405-000009" in caption


def test_a_payment_with_no_image_still_reaches_someone() -> None:
    sender = Sender()
    build(sender, operators=[1], file_id=None).on_proof_submitted(SUBMITTED)

    assert not sender.photos
    assert "بدون تصویر" in str(sender.texts[0]["text"])


def test_telegram_being_down_does_not_reach_the_publisher() -> None:
    """This runs inside the transaction that accepted the customer's receipt.

    Raising here would roll that back - the customer would lose their proof
    because we could not tell an operator about it.
    """
    build(Sender(breaks=True), operators=[1]).on_proof_submitted(SUBMITTED)


def test_no_linked_operator_is_not_an_error() -> None:
    sender = Sender()
    build(sender, operators=[]).on_proof_submitted(SUBMITTED)

    assert not sender.photos and not sender.texts


# -- both are actually subscribed ------------------------------------------
#
# The failure this whole file exists for is not a broken handler, it is a
# correct one nothing calls. Two of them, for years.


def test_both_handlers_are_wired_to_their_events() -> None:
    import ast
    from pathlib import Path

    scope = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "geekvpn"
        / "infrastructure"
        / "di"
        / "sync_scope.py"
    )
    source = ast.parse(scope.read_text(encoding="utf-8"))
    wired = {
        ast.unparse(node.value)
        for node in ast.walk(source)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Subscript)
        and ast.unparse(node.targets[0]).startswith("table[")
    }

    assert "self.delivery_notifications.on_subscription_activated" in wired
    assert "self.receipt_alerts.on_proof_submitted" in wired
