"""Application-layer encryption for data at rest.

Why this file exists at all
---------------------------
Postgres disk encryption protects against a stolen disk. It does nothing about
the far likelier incident: a leaked read-only replica, a stray ``pg_dump`` in a
backup bucket, or an SQL-injection hole in some future endpoint. Panel API
credentials, card numbers and TOTP secrets are the crown jewels of this
platform - a Marzban admin password is a live VPN infrastructure, and a card
number is a legal identity in Iran. Those columns get encrypted in the
application, so what lands in a dump is unreadable without a key the database
never sees.

Choices, and why
----------------
* **AES-256-GCM**, from ``cryptography``. I did not implement a cipher here.
  Rolling your own AES is the single most reliable way to produce something
  that looks encrypted and is not.
* **A key ring, not a key.** Every ciphertext carries the id of the key that
  produced it, so rotation is: add a new key, make it active, re-encrypt in the
  background. Without the id, rotation means a synchronous rewrite of every row
  during a maintenance window, which is why in practice nobody ever rotates.
* **Keys are derived (HKDF), not stored.** Operators manage one high-entropy
  master secret; each key id derives a distinct 256-bit key. One secret in the
  vault, many keys in the system.
* **AAD binds every ciphertext to its context.** Without it an attacker with
  write access could copy the encrypted password of a *test* panel over a
  production panel's column and authenticate against a box they control - a
  real attack that signature-less encryption does not stop.
* **Nonces are random per encryption**, never counters. GCM with a repeated
  nonce under the same key leaks the XOR of two plaintexts and, worse, the
  authentication key itself.

Searchable encryption
---------------------
``blind_index`` exists because "find the payment with this card number" is a
real support request, and randomised ciphertext cannot be looked up. A blind
index is a keyed HMAC: equality-searchable, but useless to anyone without the
key - unlike a bare SHA-256 of a card number, which is trivially brute-forced
since a card number has far less entropy than its digest suggests.
"""

from __future__ import annotations

import base64
import hmac
import re
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

#: Token layout: ``v1.<key id>.<urlsafe b64 of nonce||ciphertext||tag>``.
#: Versioned so a future move to XChaCha20 can coexist with old rows.
SCHEME: Final = "v1"
SEPARATOR: Final = "."
NONCE_BYTES: Final = 12  # 96 bits, the only nonce size GCM is proven at
KEY_BYTES: Final = 32  # AES-256
BLIND_INDEX_BYTES: Final = 16  # 128 bits of a truncated HMAC
MIN_MASTER_SECRET_CHARS: Final = 32

_KEY_ID_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_ENCRYPTION_INFO: Final = b"geekvpn/encryption/aes256gcm/v1/"
_BLIND_INDEX_INFO: Final = b"geekvpn/blind-index/hmac-sha256/v1"
_TOKEN_PREFIX: Final = SCHEME + SEPARATOR


class EncryptionError(RuntimeError):
    """Base class. Never carries plaintext or key material in its message."""


class EncryptionConfigError(EncryptionError):
    """The key ring itself is misconfigured - a boot-time failure."""


class UnknownKeyError(EncryptionError):
    """Ciphertext references a key id this deployment does not hold.

    Almost always means a retired key was dropped from configuration while rows
    encrypted under it still exist. Recoverable by putting the key back, which
    is exactly why the id travels with the ciphertext.
    """


class DecryptionError(EncryptionError):
    """Authentication failed: wrong key, wrong context, or tampering.

    Deliberately does not distinguish between those causes in its message. A
    decryption oracle that says *why* it refused is a decryption oracle.
    """


def derive_key(master_secret: str, *, key_id: str) -> bytes:
    """Derive the 256-bit data key for ``key_id`` from the master secret."""
    _validate_key_id(key_id)
    if len(master_secret) < MIN_MASTER_SECRET_CHARS:
        raise EncryptionConfigError(
            f"The encryption master secret must be at least {MIN_MASTER_SECRET_CHARS} characters."
        )
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=None,
        info=_ENCRYPTION_INFO + key_id.encode("ascii"),
    )
    return kdf.derive(master_secret.encode("utf-8"))


def _derive_blind_index_key(master_secret: str) -> bytes:
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=None,
        info=_BLIND_INDEX_INFO,
    )
    return kdf.derive(master_secret.encode("utf-8"))


def _validate_key_id(key_id: str) -> None:
    if not _KEY_ID_PATTERN.match(key_id):
        # The id goes into the AAD and into the token; a dot would make the
        # token ambiguous to parse.
        raise EncryptionConfigError(
            "Key ids must be lowercase alphanumeric with - or _, 1-32 chars."
        )


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise DecryptionError("Malformed ciphertext.") from exc


def is_ciphertext(value: str | None) -> bool:
    """True when ``value`` looks like a token produced by this module.

    Exists so a backfill migration can encrypt a column in place and be safely
    re-run: already-encrypted rows are skipped instead of double-encrypted.
    """
    if not value or not value.startswith(_TOKEN_PREFIX):
        return False
    return len(value.split(SEPARATOR)) == 3


@dataclass(frozen=True, slots=True)
class DataKey:
    key_id: str
    material: bytes

    def __post_init__(self) -> None:
        _validate_key_id(self.key_id)
        if len(self.material) != KEY_BYTES:
            raise EncryptionConfigError(f"Data keys must be {KEY_BYTES} bytes.")

    def __repr__(self) -> str:  # pragma: no cover - defensive
        # Never let key material reach a log line or a traceback.
        return f"DataKey(key_id={self.key_id!r}, material=<redacted>)"


class KeyRing:
    """Holds the active key plus every retired key still needed for reads."""

    __slots__ = ("_active_key_id", "_blind_index_key", "_keys")

    def __init__(
        self,
        keys: Iterable[DataKey],
        *,
        active_key_id: str,
        blind_index_key: bytes,
    ) -> None:
        by_id = {key.key_id: key for key in keys}
        if not by_id:
            raise EncryptionConfigError("A key ring needs at least one key.")
        if active_key_id not in by_id:
            raise EncryptionConfigError(
                f"Active key id {active_key_id!r} is not present in the key ring."
            )
        if len(blind_index_key) != KEY_BYTES:
            raise EncryptionConfigError(f"The blind index key must be {KEY_BYTES} bytes.")
        self._keys: Mapping[str, DataKey] = by_id
        self._active_key_id = active_key_id
        self._blind_index_key = blind_index_key

    @classmethod
    def from_master_secret(
        cls,
        master_secret: str,
        *,
        active_key_id: str = "k1",
        retired_key_ids: Iterable[str] = (),
    ) -> KeyRing:
        """Build a ring by deriving every key id from one master secret."""
        ids = [active_key_id, *dict.fromkeys(retired_key_ids)]
        keys = [
            DataKey(key_id=key_id, material=derive_key(master_secret, key_id=key_id))
            for key_id in dict.fromkeys(ids)
        ]
        return cls(
            keys,
            active_key_id=active_key_id,
            blind_index_key=_derive_blind_index_key(master_secret),
        )

    @property
    def active_key_id(self) -> str:
        return self._active_key_id

    @property
    def key_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._keys))

    def encrypt(self, plaintext: str, *, context: str) -> str:
        """Encrypt under the active key, bound to ``context``.

        ``context`` should identify the column and the row, for example
        ``"panel:credentials:<panel id>"``. It is not secret; it is a label the
        ciphertext cannot be separated from.
        """
        if not context:
            # An empty AAD silently removes the binding this whole design rests
            # on, so it is a programming error, not a default.
            raise EncryptionConfigError("An encryption context is required.")
        key = self._keys[self._active_key_id]
        nonce = secrets.token_bytes(NONCE_BYTES)
        sealed = AESGCM(key.material).encrypt(
            nonce,
            plaintext.encode("utf-8"),
            _aad(context=context, key_id=key.key_id),
        )
        return SEPARATOR.join((SCHEME, key.key_id, _b64encode(nonce + sealed)))

    def decrypt(self, token: str, *, context: str) -> str:
        key_id, nonce, sealed = self._parse(token)
        key = self._keys.get(key_id)
        if key is None:
            raise UnknownKeyError(f"No key with id {key_id!r} is configured.")
        try:
            plaintext = AESGCM(key.material).decrypt(
                nonce, sealed, _aad(context=context, key_id=key_id)
            )
        except InvalidTag as exc:
            raise DecryptionError("Ciphertext failed authentication.") from exc
        return plaintext.decode("utf-8")

    def needs_rotation(self, token: str) -> bool:
        """True when the ciphertext was produced by a non-active key."""
        key_id, _, _ = self._parse(token)
        return key_id != self._active_key_id

    def rewrap(self, token: str, *, context: str) -> str:
        """Re-encrypt an old ciphertext under the active key."""
        return self.encrypt(self.decrypt(token, context=context), context=context)

    def blind_index(self, value: str, *, context: str) -> str:
        """Deterministic, keyed, equality-searchable digest of ``value``.

        Truncated to 128 bits: collisions are irrelevant here because the row is
        confirmed by decrypting it, and a shorter index means a smaller b-tree.
        """
        message = f"{context}|{value}".encode()
        digest = hmac.new(self._blind_index_key, message, sha256).digest()
        return digest[:BLIND_INDEX_BYTES].hex()

    def _parse(self, token: str) -> tuple[str, bytes, bytes]:
        parts = token.split(SEPARATOR)
        if len(parts) != 3 or parts[0] != SCHEME:
            raise DecryptionError("Unrecognised ciphertext format.")
        raw = _b64decode(parts[2])
        if len(raw) <= NONCE_BYTES:
            raise DecryptionError("Ciphertext is too short to be valid.")
        return parts[1], raw[:NONCE_BYTES], raw[NONCE_BYTES:]


def _aad(*, context: str, key_id: str) -> bytes:
    return f"{SCHEME}|{key_id}|{context}".encode()


def digits_only(value: str) -> str:
    """Normalise a card number or txid before indexing it.

    Persian and Arabic-Indic digits are folded to ASCII first: a customer who
    pastes a card number from a Persian banking app must hit the same index
    entry as one who types it on a Latin keyboard.
    """
    folded = value.translate(_DIGIT_FOLD)
    return "".join(char for char in folded if char.isdigit())


_DIGIT_FOLD: Final = {
    **{0x0660 + offset: str(offset) for offset in range(10)},  # Arabic-Indic
    **{0x06F0 + offset: str(offset) for offset in range(10)},  # Persian
}


def mask_card(card_number: str) -> str:
    """``6037********1234`` - what an operator is allowed to see.

    The first six digits are the BIN, which only identifies the bank, and the
    last four are what a customer recognises. The middle is the part that lets
    someone actually charge the card, so it never reaches a screen or a log.
    """
    digits = digits_only(card_number)
    if len(digits) < 10:
        return "*" * len(digits)
    return f"{digits[:6]}{'*' * (len(digits) - 10)}{digits[-4:]}"


def constant_time_equals(left: str, right: str) -> bool:
    """Compare two secrets without leaking their common prefix length."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


__all__ = [
    "BLIND_INDEX_BYTES",
    "KEY_BYTES",
    "MIN_MASTER_SECRET_CHARS",
    "NONCE_BYTES",
    "SCHEME",
    "DataKey",
    "DecryptionError",
    "EncryptionConfigError",
    "EncryptionError",
    "KeyRing",
    "UnknownKeyError",
    "constant_time_equals",
    "derive_key",
    "digits_only",
    "is_ciphertext",
    "mask_card",
]
