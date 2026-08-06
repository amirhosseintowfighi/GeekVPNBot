"""SQLAlchemy column types for data that must not sit in the clear.

The pattern here is deliberately two columns, not one:

* an ``EncryptedString`` column holding the ciphertext, and
* a ``BlindIndex`` column holding a keyed HMAC of the normalised value.

One column cannot do both jobs. AES-GCM uses a fresh nonce per encryption, so
the same card number encrypts to a different string every time — which is the
whole point, and which also means ``WHERE card_encrypted = :value`` can never
match. The blind index is deterministic, so equality lookups work, and because
it is a keyed HMAC rather than a plain hash, someone holding a database dump
without the key cannot enumerate the sixteen-digit card space against it.

The keyring is supplied by a callable rather than passed in directly. Column
types are constructed at import time, when the settings and container do not
exist yet; resolving the keyring lazily on first use is what lets the model
modules stay importable without a configured application.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from geekvpn.infrastructure.security.crypto import (
    BLIND_INDEX_BYTES,
    KeyRing,
    digits_only,
    is_ciphertext,
)

#: Length of a hex-encoded blind index: ``BLIND_INDEX_BYTES`` doubled.
#:
#: Derived from crypto.py rather than written as a literal. The first version of
#: this module hard-coded 64 for both this and the column width, on the
#: assumption that a sha256-based digest is 64 hex characters. It is not — the
#: blind index is truncated to 16 bytes — so the "this value is already a digest"
#: check below never fired, and a digest passed back into a query would have been
#: digested a second time and matched nothing. Caught by asserting the real
#: length against the real function.
BLIND_INDEX_LENGTH = BLIND_INDEX_BYTES * 2

#: Declared width of the database column, per migration 0004. Wider than the
#: digest on purpose: a future move to a full-length digest becomes a constant
#: change rather than a table rewrite on a live payments table.
BLIND_INDEX_COLUMN_LENGTH = 64

_keyring_provider: Callable[[], KeyRing] | None = None


class EncryptionNotConfiguredError(RuntimeError):
    """Raised when an encrypted column is used before a keyring is installed.

    This is a loud failure on purpose. The quiet alternative — falling back to
    storing the plaintext — is how encrypted columns end up containing clear
    data in production while every test passes.
    """


def install_keyring(provider: Callable[[], KeyRing]) -> None:
    """Register how encrypted columns should obtain the keyring.

    Called once during application start-up, after the container is built::

        install_keyring(lambda: container.keyring)
    """
    global _keyring_provider
    _keyring_provider = provider


def reset_keyring() -> None:
    """Forget the installed keyring. For tests that must assert the failure."""
    global _keyring_provider
    _keyring_provider = None


def current_keyring() -> KeyRing:
    if _keyring_provider is None:
        raise EncryptionNotConfiguredError(
            "No keyring installed. Call install_keyring() during start-up before "
            "reading or writing an encrypted column."
        )
    return _keyring_provider()


class EncryptedString(TypeDecorator[str]):
    """Text column whose Python value is plaintext and whose stored value is not.

    ``context`` is bound into the AEAD associated data, so a ciphertext lifted
    out of ``billing_card_accounts`` cannot be pasted into a panel-credentials
    column and decrypted there. Getting that wrong is the usual way
    envelope encryption fails in practice.
    """

    impl = Text
    cache_ok = True

    def __init__(self, context: str, **kwargs: Any) -> None:
        if not context or not context.strip():
            raise ValueError("EncryptedString requires a non-empty context.")
        self.context = context
        super().__init__(**kwargs)

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if is_ciphertext(value):
            # Already encrypted. This happens on a re-save of a row that was
            # loaded, rewrapped by a rotation job, and never decrypted. Encrypting
            # again would produce an undecryptable double-wrapped token.
            return value
        return current_keyring().encrypt(value, context=self.context)

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if not is_ciphertext(value):
            # A plaintext value predating the migration. Returning it is correct
            # during the backfill window; refusing would take the application
            # down for every not-yet-migrated row.
            return value
        return current_keyring().decrypt(value, context=self.context)

    def copy(self, **kwargs: Any) -> EncryptedString:
        return EncryptedString(self.context)


class EncryptedCard(EncryptedString):
    """An encrypted card number, normalised to digits before storage.

    Users paste card numbers with spaces, dashes and Persian digits. Storing
    those variations verbatim means the blind index of the same card differs by
    how it was typed, and duplicate detection silently stops working.
    """

    cache_ok = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("card", **kwargs)

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None or is_ciphertext(value):
            return super().process_bind_param(value, dialect)
        return super().process_bind_param(digits_only(value), dialect)

    def copy(self, **kwargs: Any) -> EncryptedCard:
        return EncryptedCard()


class BlindIndex(TypeDecorator[str]):
    """Deterministic keyed digest of a value, for equality lookups only.

    Only equality. Ordering and range queries over a digest are meaningless, and
    ``LIKE`` against it will match nothing, which is worth stating because a
    partial-match search against a blind index is a bug that looks like an empty
    result set rather than an error.
    """

    impl = String(BLIND_INDEX_COLUMN_LENGTH)
    cache_ok = True

    @staticmethod
    def looks_like_digest(value: str) -> bool:
        """Whether ``value`` is already a computed index rather than a raw value.

        Compared against the real digest length, not an assumed one.
        """
        return len(value) == BLIND_INDEX_LENGTH and all(
            character in "0123456789abcdef" for character in value
        )

    def __init__(self, context: str, *, normalise_digits: bool = False, **kwargs: Any) -> None:
        if not context or not context.strip():
            raise ValueError("BlindIndex requires a non-empty context.")
        self.context = context
        self.normalise_digits = normalise_digits
        super().__init__(**kwargs)

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if self.looks_like_digest(value):
            # Already a digest, so a caller queried with an index they computed
            # themselves via blind_index_of(). Digesting it again would search
            # for the hash of the hash.
            return value
        subject = digits_only(value) if self.normalise_digits else value.strip()
        return current_keyring().blind_index(subject, context=self.context)

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        # A digest is one-way; the stored value is the value.
        return value

    def copy(self, **kwargs: Any) -> BlindIndex:
        return BlindIndex(self.context, normalise_digits=self.normalise_digits)


class CardBlindIndex(BlindIndex):
    """Blind index over a card number, matching :class:`EncryptedCard`."""

    cache_ok = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("card", normalise_digits=True, **kwargs)

    def copy(self, **kwargs: Any) -> CardBlindIndex:
        return CardBlindIndex()


def blind_index_of(value: str, *, context: str, normalise_digits: bool = False) -> str:
    """Compute a blind index outside the ORM, for building a query filter."""
    subject = digits_only(value) if normalise_digits else value.strip()
    return current_keyring().blind_index(subject, context=context)


def card_blind_index_of(card_number: str) -> str:
    """Blind index for a card number, for ``WHERE card_blind_index = :index``."""
    return blind_index_of(card_number, context="card", normalise_digits=True)


__all__ = [
    "BLIND_INDEX_COLUMN_LENGTH",
    "BLIND_INDEX_LENGTH",
    "BlindIndex",
    "CardBlindIndex",
    "EncryptedCard",
    "EncryptedString",
    "EncryptionNotConfiguredError",
    "blind_index_of",
    "card_blind_index_of",
    "current_keyring",
    "install_keyring",
    "reset_keyring",
]
