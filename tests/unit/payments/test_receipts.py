"""Receipt upload validation and fingerprinting."""

from __future__ import annotations

import pytest

from geekvpn.application.payments.receipts import (
    MAX_RECEIPT_BYTES,
    ReceiptService,
    ReceiptUpload,
)
from geekvpn.domain.payments.enums import PaymentMethod
from geekvpn.domain.payments.errors import PaymentValidationError
from tests.unit.payments.fakes import EPOCH, FakeStorage

IMAGE = b"\xff\xd8\xff\xe0 fake jpeg bytes"


def _service() -> tuple[ReceiptService, FakeStorage]:
    storage = FakeStorage()
    return ReceiptService(storage=storage), storage


def _upload(**overrides) -> ReceiptUpload:
    data = {
        "payment_id": "pay-1",
        "content": IMAGE,
        "mime_type": "image/jpeg",
        "file_id": "AgACAgQ-1",
    }
    data.update(overrides)
    return ReceiptUpload(**data)


def test_an_accepted_receipt_is_stored_and_fingerprinted():
    service, storage = _service()
    proof = service.accept(_upload(), submitted_at=EPOCH)
    assert proof.method is PaymentMethod.CARD
    assert proof.digest
    assert storage.saved[proof.reference] == IMAGE


def test_the_same_image_forwarded_produces_the_same_digest():
    """The fraud case: one genuine receipt forwarded against several orders.

    Telegram gives the forwarded photo a new file id, so only a hash of the
    bytes catches it.
    """
    service, _ = _service()
    first = service.accept(_upload(file_id="original"), submitted_at=EPOCH)
    second = service.accept(_upload(file_id="forwarded"), submitted_at=EPOCH)
    assert first.file_id != second.file_id
    assert first.digest == second.digest


def test_a_different_image_produces_a_different_digest():
    service, _ = _service()
    first = service.accept(_upload(), submitted_at=EPOCH)
    second = service.accept(_upload(content=IMAGE + b"x"), submitted_at=EPOCH)
    assert first.digest != second.digest


def test_an_empty_upload_is_rejected():
    service, _ = _service()
    with pytest.raises(PaymentValidationError):
        service.accept(_upload(content=b""), submitted_at=EPOCH)


def test_an_over_large_upload_is_rejected():
    service, _ = _service()
    with pytest.raises(PaymentValidationError):
        service.accept(_upload(content=b"x" * (MAX_RECEIPT_BYTES + 1)), submitted_at=EPOCH)


def test_an_unexpected_file_type_is_rejected():
    service, _ = _service()
    with pytest.raises(PaymentValidationError):
        service.accept(_upload(mime_type="application/zip"), submitted_at=EPOCH)


def test_bank_pdf_receipts_are_accepted():
    """Iranian bank apps export receipts as PDF, not only as photos."""
    service, _ = _service()
    proof = service.accept(_upload(mime_type="application/pdf"), submitted_at=EPOCH)
    assert proof.digest


def test_nothing_is_stored_when_validation_fails():
    """A rejected upload must not leave litter in storage."""
    service, storage = _service()
    with pytest.raises(PaymentValidationError):
        service.accept(_upload(mime_type="application/zip"), submitted_at=EPOCH)
    assert storage.saved == {}
