"""Receipt upload.

The rule that shapes this file: **the fingerprint is taken from the image
bytes, never from the Telegram file id.**

Forwarding a photo in Telegram produces a new ``file_id`` for identical
pixels. A duplicate check keyed on the file id therefore catches nothing,
which is precisely the case a fraudster exercises: send one receipt, forward
it for the next three orders. Hashing the downloaded bytes catches it.

The storage port takes bytes and returns a locator, so the same service works
whether receipts live on disk, in object storage, or behind a CDN.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, runtime_checkable

from geekvpn.domain.payments.enums import PaymentMethod
from geekvpn.domain.payments.errors import PaymentValidationError
from geekvpn.domain.payments.proof import PaymentProof

MAX_RECEIPT_BYTES: Final[int] = 5 * 1024 * 1024
"""Telegram photos sit far below this. The limit exists to stop a document
upload becoming a denial-of-service, not to inconvenience anyone."""

ALLOWED_MIME: Final[frozenset[str]] = frozenset(
    {"image/jpeg", "image/png", "image/webp", "application/pdf"}
)
"""PDF is allowed because Iranian bank apps export receipts that way."""


@runtime_checkable
class ReceiptStorage(Protocol):
    """Somewhere durable to keep receipt images.

    Receipts are evidence in a financial dispute, so they must outlive the
    Telegram file id, which expires.
    """

    def store(self, *, payment_id: str, content: bytes, mime_type: str) -> str:
        """Persist the bytes and return a stable locator."""
        ...

    def url_for(self, locator: str) -> str: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ReceiptUpload:
    payment_id: str
    content: bytes
    mime_type: str
    file_id: str | None = None
    note_fa: str | None = None


class ReceiptService:
    """Validates, stores, and fingerprints an uploaded receipt."""

    __slots__ = ("_storage",)

    def __init__(self, *, storage: ReceiptStorage) -> None:
        self._storage = storage

    def accept(self, upload: ReceiptUpload, *, submitted_at: datetime) -> PaymentProof:
        if not upload.content:
            raise PaymentValidationError("The uploaded receipt is empty.")
        if len(upload.content) > MAX_RECEIPT_BYTES:
            raise PaymentValidationError(
                "The receipt file is too large.",
                size=len(upload.content),
                maximum=MAX_RECEIPT_BYTES,
            )
        if upload.mime_type not in ALLOWED_MIME:
            raise PaymentValidationError(
                "That file type is not accepted as a receipt.",
                mime_type=upload.mime_type,
            )

        # Hash first, store second. If storage fails we have not yet claimed
        # to hold a receipt; if hashing fails there is nothing worth storing.
        #
        # Hashed directly rather than through ``proof.fingerprint``: that
        # helper canonicalises *text* (casing, Persian digits, a leading 0x)
        # before hashing, which is right for a transaction hash typed by a
        # human and meaningless for binary image data. Bytes are already
        # canonical.
        digest = hashlib.sha256(upload.content).hexdigest()
        locator = self._storage.store(
            payment_id=upload.payment_id,
            content=upload.content,
            mime_type=upload.mime_type,
        )

        return PaymentProof(
            method=PaymentMethod.CARD,
            reference=locator,
            digest=digest,
            submitted_at=submitted_at,
            file_id=upload.file_id,
            note_fa=upload.note_fa,
        )


__all__ = [
    "ALLOWED_MIME",
    "MAX_RECEIPT_BYTES",
    "ReceiptService",
    "ReceiptStorage",
    "ReceiptUpload",
]
