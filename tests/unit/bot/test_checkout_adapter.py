"""The bot's checkout adapter.

This is the only bot adapter that moves money, so the behaviours pinned here are
the ones whose failure costs real Toman: the receipt fingerprint, and the link
between an order and the invoice that pays for it.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest

from geekvpn.application.bot import ports
from geekvpn.domain.payments.proof import PaymentProof
from geekvpn.infrastructure.bot.checkout import BotCheckoutAdapter


class NoUserBridge:
    async def telegram_id(self, user_id: uuid.UUID) -> int | None:
        return None

    async def run(self, work: object) -> object:  # pragma: no cover
        raise AssertionError("The sync scope must not be opened for an unknown user.")


def build(**overrides: object) -> BotCheckoutAdapter:
    kwargs: dict[str, object] = {
        "bridge": NoUserBridge(),
        "quoting": object(),
        "orders": object(),
        "order_repository": object(),
        "provisioning": object(),
        "session": object(),
        "plans": object(),
        "clock": object(),
        "jalali_year": 1405,
    }
    kwargs.update(overrides)
    return BotCheckoutAdapter(**kwargs)  # type: ignore[arg-type]


def test_the_adapter_satisfies_the_checkout_port() -> None:
    assert isinstance(build(), ports.CheckoutService)


# -- the receipt fingerprint ----------------------------------------------


class KnownUser(NoUserBridge):
    """A bridge whose customer exists, so ownership resolves."""

    async def telegram_id(self, user_id: uuid.UUID) -> int:
        return 555


async def test_a_receipt_is_refused_when_it_cannot_be_fingerprinted() -> None:
    """Never fall back to hashing the file id.

    Forwarding a photo yields a fresh file id for identical bytes, so a file-id
    digest would make a resubmitted receipt look new and silently defeat the
    duplicate-receipt control that docs/security.md calls the primary defence.
    """
    adapter = build(bridge=KnownUser(), fetch_receipt=None)

    with pytest.raises(RuntimeError, match="fingerprinted"):
        await adapter.attach_receipt(uuid.uuid4(), payment_id=uuid.uuid4(), file_id="AgAC")


async def test_the_fingerprint_is_taken_from_the_bytes_not_the_file_id() -> None:
    image = b"\x89PNG-receipt-bytes"
    captured: dict[str, str] = {}

    async def fetch(file_id: str) -> bytes:
        captured["file_id"] = file_id
        return image

    class Clock:
        def now(self):
            from datetime import UTC, datetime

            return datetime(2026, 8, 7, tzinfo=UTC)

    class Bridge(KnownUser):
        async def run(self, work):
            return work(_ScopeStub())

    class _Checkout:
        submitted: PaymentProof | None = None

        def submit_proof(self, *, payment_id: str, proof: PaymentProof, user_id=None):
            _Checkout.submitted = proof
            return _Payment()

    class _Payment:
        id = str(uuid.uuid4())
        amount = type("M", (), {"amount": 1000})()
        method = __import__(
            "geekvpn.domain.payments.enums", fromlist=["PaymentMethod"]
        ).PaymentMethod.CARD
        state = __import__(
            "geekvpn.domain.payments.enums", fromlist=["PaymentState"]
        ).PaymentState.PENDING_REVIEW
        created_at = None

    class _ScopeStub:
        checkout = _Checkout()

    adapter = build(bridge=Bridge(), clock=Clock(), fetch_receipt=fetch)

    await adapter.attach_receipt(uuid.uuid4(), payment_id=uuid.uuid4(), file_id="AgACfwd")

    assert captured["file_id"] == "AgACfwd"
    assert _Checkout.submitted is not None
    assert _Checkout.submitted.digest == hashlib.sha256(image).hexdigest()


async def test_the_same_image_under_two_file_ids_produces_one_digest() -> None:
    """The property the duplicate-receipt constraint actually relies on."""
    image = b"identical-bytes"

    first = PaymentProof.for_card(
        file_id="AgACoriginal",
        image_digest=hashlib.sha256(image).hexdigest(),
        submitted_at=__import__("datetime").datetime(2026, 8, 7, tzinfo=__import__("datetime").UTC),
    )
    second = PaymentProof.for_card(
        file_id="AgACforwarded",
        image_digest=hashlib.sha256(image).hexdigest(),
        submitted_at=__import__("datetime").datetime(2026, 8, 7, tzinfo=__import__("datetime").UTC),
    )

    assert first.file_id != second.file_id
    assert first.digest == second.digest


# -- unimplemented paths are loud -----------------------------------------


async def test_wallet_checkout_refuses_an_unknown_customer_like_every_other_method() -> None:
    with pytest.raises(LookupError):
        await build().pay_from_wallet(uuid.uuid4(), plan_id=uuid.uuid4())


def test_wallet_checkout_expires_the_session_before_provisioning() -> None:
    """The order is marked PAID by the *other* scope.

    This session created it moments ago and still holds the PENDING copy, so
    without expiring the identity map `provision` reads a stale state and
    refuses - which would make wallet checkout fail every single time.
    """
    import inspect

    source = inspect.getsource(BotCheckoutAdapter.pay_from_wallet)
    assert "expire_all()" in source
    assert source.index("expire_all()") < source.index("provision(")


async def test_an_unknown_customer_cannot_start_a_payment() -> None:
    with pytest.raises(LookupError):
        await build().begin_card(uuid.uuid4(), plan_id=uuid.uuid4())
