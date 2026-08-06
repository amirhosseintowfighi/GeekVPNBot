"""Proof of a manual payment.

Two shapes of evidence, one type. A card-to-card payment is proved by a photo
of a bank receipt; a crypto payment is proved by a transaction hash. They are
modelled together because everything the system does with them is the same:
fingerprint it, reject duplicates, show it to a reviewer, keep it forever.

The fingerprint is the whole point of this module. The commonest fraud in
card-to-card sales is forwarding one genuine receipt against three orders,
and a reviewer looking at a photo has no way to know they have seen it before.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from geekvpn.domain.payments.enums import PaymentMethod
from geekvpn.domain.payments.errors import PaymentValidationError

MIN_TXID_LENGTH: Final[int] = 10
"""Shortest plausible on-chain hash. Matches the bot's own validation so a
customer is never told "looks fine" by one layer and "too short" by the next."""

MAX_TXID_LENGTH: Final[int] = 128

MAX_NOTE_LENGTH: Final[int] = 500

_TXID_ALLOWED: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9:_-]+$")
"""Hex for most chains, base58 for some, colons for chain-prefixed ids. No
whitespace: a pasted hash with a stray newline must be cleaned, not accepted,
or two spellings of one hash will both pass the duplicate check."""

_PERSIAN_DIGITS: Final[dict[int, int]] = {
    **{ord("\u06f0") + index: ord("0") + index for index in range(10)},
    **{ord("\u0660") + index: ord("0") + index for index in range(10)},
}
"""Persian and Arabic-Indic digits to ASCII.

Customers paste transaction hashes from wallet apps that localise digits. The
same hash typed on two phones must fingerprint identically, so normalisation
happens before hashing, not after.
"""


def normalise_reference(raw: str) -> str:
    """Canonical form of a user-supplied reference.

    Lowercased, digit-normalised, whitespace and a leading ``0x`` stripped.
    Two customers submitting the same hash in different casing must collide,
    otherwise the duplicate check is decorative.
    """
    text = raw.strip().translate(_PERSIAN_DIGITS)
    text = "".join(text.split())
    text = text.lower()
    if text.startswith("0x"):
        text = text[2:]
    return text


def fingerprint(value: str) -> str:
    """Stable hash used for duplicate detection.

    SHA-256 of the canonical form. Storing the digest rather than the raw
    value means the uniqueness index cannot be defeated by casing, and means
    an image fingerprint and a hash fingerprint live in one column.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentProof:
    """What the customer submitted so a human, or a chain, can confirm payment."""

    method: PaymentMethod
    reference: str
    """Canonicalised tx hash, or the storage key of the receipt image."""

    digest: str
    """Fingerprint of the *content*: the hash itself, or the image bytes."""

    submitted_at: datetime
    file_id: str | None = None
    """Telegram file id for card receipts. Telegram file ids are not stable
    forever, which is exactly why the digest is stored separately."""

    network: str | None = None
    note_fa: str | None = None

    def __post_init__(self) -> None:
        if not self.reference:
            raise PaymentValidationError("A payment proof needs a reference.")
        if self.note_fa is not None and len(self.note_fa) > MAX_NOTE_LENGTH:
            raise PaymentValidationError(
                "The note attached to the receipt is too long.",
                length=len(self.note_fa),
                maximum=MAX_NOTE_LENGTH,
            )

    @classmethod
    def for_card(
        cls,
        *,
        file_id: str,
        image_digest: str,
        submitted_at: datetime,
        note_fa: str | None = None,
    ) -> PaymentProof:
        """Build proof from an uploaded receipt image.

        ``image_digest`` is computed by the infrastructure layer from the
        downloaded bytes, not from the Telegram file id. Forwarding a photo
        produces a new file id but identical bytes, and it is the bytes that
        betray the reuse.
        """
        if not file_id.strip():
            raise PaymentValidationError("The receipt file is missing.")
        if not image_digest.strip():
            raise PaymentValidationError("The receipt could not be fingerprinted.")
        return cls(
            method=PaymentMethod.CARD,
            reference=file_id.strip(),
            digest=image_digest.strip().lower(),
            file_id=file_id.strip(),
            submitted_at=submitted_at,
            note_fa=(note_fa.strip() if note_fa and note_fa.strip() else None),
        )

    @classmethod
    def for_crypto(
        cls,
        *,
        txid: str,
        network: str,
        submitted_at: datetime,
        note_fa: str | None = None,
    ) -> PaymentProof:
        """Build proof from an on-chain transaction hash."""
        canonical = normalise_reference(txid)
        if len(canonical) < MIN_TXID_LENGTH:
            raise PaymentValidationError(
                "That transaction hash is too short to be real.",
                length=len(canonical),
                minimum=MIN_TXID_LENGTH,
            )
        if len(canonical) > MAX_TXID_LENGTH:
            raise PaymentValidationError(
                "That transaction hash is too long.",
                length=len(canonical),
                maximum=MAX_TXID_LENGTH,
            )
        if not _TXID_ALLOWED.match(canonical):
            raise PaymentValidationError("That transaction hash contains unexpected characters.")
        if not network.strip():
            raise PaymentValidationError("The crypto network must be specified.")
        return cls(
            method=PaymentMethod.CRYPTO,
            reference=canonical,
            digest=fingerprint(canonical),
            network=network.strip().lower(),
            submitted_at=submitted_at,
            note_fa=(note_fa.strip() if note_fa and note_fa.strip() else None),
        )


__all__ = [
    "MAX_NOTE_LENGTH",
    "MAX_TXID_LENGTH",
    "MIN_TXID_LENGTH",
    "PaymentProof",
    "fingerprint",
    "normalise_reference",
]
