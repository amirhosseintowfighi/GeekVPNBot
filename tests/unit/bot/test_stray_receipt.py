"""A receipt photo sent with no flow behind it must still reach its payment.

A card payment started in the Mini App ends with a button that closes the app.
The customer is then in the chat with no FSM state, so the photo they were
told to send matched only the catch-all handler and got "I did not understand
that". They had transferred the money and no way to prove it, and the payment
stayed in AWAITING_PROOF - a state the review queue does not show, so it was
invisible to the operator as well. Both halves of "nothing happens" came from
this one gap.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from geekvpn.application.bot.read_models import PaymentMethod, PaymentState, PendingPayment
from geekvpn.application.payments.receipt_intent import receipt_intent_key
from geekvpn.presentation.bot.handlers.fallback import stray_receipt
from geekvpn.presentation.bot.ui import text as T

pytestmark = pytest.mark.unit


class Photo:
    def __init__(self, file_id: str) -> None:
        self.file_id = file_id


class Message:
    """Just enough of an aiogram Message for this handler."""

    def __init__(self, photo: list[Photo] | None) -> None:
        self.photo = photo
        self.replies: list[str] = []

    async def answer(self, text: str, **_: object) -> None:
        self.replies.append(text)


class Cache:
    """The shared cache the Mini App writes a receipt intent into."""

    def __init__(self, stored: dict[str, str] | None = None) -> None:
        self.stored = dict(stored or {})

    async def get(self, key: str) -> str | None:
        return self.stored.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        self.stored[key] = value

    async def delete(self, key: str) -> None:
        self.stored.pop(key, None)

    async def add_if_absent(self, key: str, value: str, *, ttl_seconds: int) -> bool:
        return self.stored.setdefault(key, value) == value


class State:
    def __init__(self) -> None:
        self.cleared = False

    async def clear(self) -> None:
        self.cleared = True


class Checkout:
    def __init__(self, pending: list[PendingPayment]) -> None:
        self._pending = pending
        self.attached: tuple[uuid.UUID, str] | None = None

    async def awaiting_proof(self, user_id: uuid.UUID) -> list[PendingPayment]:
        return self._pending

    async def attach_receipt(
        self, user_id: uuid.UUID, *, payment_id: uuid.UUID, file_id: str
    ) -> PendingPayment:
        self.attached = (payment_id, file_id)
        return self._pending[0]


class Services:
    def __init__(self, checkout: Checkout) -> None:
        self.checkout = checkout


class User:
    id = uuid.UUID(int=7)
    telegram_id = 87791922


def payment(reference: str = "1405-00009") -> PendingPayment:
    return PendingPayment(
        payment_id=uuid.uuid4(),
        reference=reference,
        amount=200_000,
        method=PaymentMethod.CARD,
        state=PaymentState.AWAITING_PROOF,
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
    )


async def run(
    pending: list[PendingPayment], *, intent: PendingPayment | None = None
) -> tuple[Message, Checkout, Cache]:
    message = Message([Photo("small"), Photo("largest")])
    checkout = Checkout(pending)
    cache = Cache(
        {receipt_intent_key(User.telegram_id): intent.payment_id.hex} if intent else {}
    )
    await stray_receipt(
        message,
        State(),
        Services(checkout),  # type: ignore[arg-type]
        cache,  # type: ignore[arg-type]
        User(),
    )
    return message, checkout, cache


async def test_the_only_waiting_payment_gets_the_receipt() -> None:
    waiting = payment()
    message, checkout, _ = await run([waiting])

    assert checkout.attached is not None
    assert checkout.attached[0] == waiting.payment_id
    assert "1405-00009" in message.replies[0]


async def test_the_highest_resolution_photo_is_the_one_sent() -> None:
    """An operator has to read a reference number off it."""
    _, checkout, _ = await run([payment()])

    assert checkout.attached is not None
    assert checkout.attached[1] == "largest"


async def test_a_photo_with_nothing_waiting_is_explained_not_attached() -> None:
    message, checkout, _ = await run([])

    assert checkout.attached is None
    assert message.replies == [T.PAY_RECEIPT_NO_PENDING]


async def test_two_waiting_payments_are_never_guessed_between() -> None:
    """Attaching the wrong receipt gets the wrong order approved."""
    message, checkout, _ = await run([payment("A"), payment("B")])

    assert checkout.attached is None
    assert message.replies == [T.PAY_RECEIPT_AMBIGUOUS]


# -- the intent the Mini App leaves behind ---------------------------------


async def test_the_customer_is_not_asked_when_they_already_said_which() -> None:
    """The point of the intent: two open payments, no question."""
    first, second = payment("A"), payment("B")
    message, checkout, _ = await run([first, second], intent=second)

    assert checkout.attached is not None
    assert checkout.attached[0] == second.payment_id
    assert T.PAY_RECEIPT_AMBIGUOUS not in message.replies


async def test_the_intent_is_spent_once() -> None:
    """Left behind, it would claim the next receipt for a payment that is
    already proven."""
    waiting = payment()
    _, _, cache = await run([waiting], intent=waiting)

    assert cache.stored == {}


async def test_a_stale_intent_does_not_select_a_payment_that_closed() -> None:
    """It is a hint, checked against what is actually open."""
    closed, still_open = payment("closed"), payment("open")
    _, checkout, _ = await run([still_open], intent=closed)

    # One payment left, so the guess is safe and the receipt still lands.
    assert checkout.attached is not None
    assert checkout.attached[0] == still_open.payment_id


async def test_a_stale_intent_with_two_open_payments_still_asks() -> None:
    """Falling back to a guess here is how the wrong order gets approved."""
    message, checkout, _ = await run([payment("A"), payment("B")], intent=payment("gone"))

    assert checkout.attached is None
    assert message.replies == [T.PAY_RECEIPT_AMBIGUOUS]
