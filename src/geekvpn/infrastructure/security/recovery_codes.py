"""Single-use recovery codes for administrators who lose their TOTP device.

Without these, a lost phone means a database edit by whoever has production
access - which is both an outage and the least auditable privilege escalation
path in the system. With them, recovery is a normal, logged, self-service act.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Final

#: Ten codes: enough that a person can lose a printout and still recover, few
#: enough to fit on one line of a page a human will actually keep.
CODE_COUNT: Final = 10

#: Two groups of four from a 32-character alphabet is ~40 bits. Combined with
#: the login rate limit that is far beyond online guessing, and it stays short
#: enough to type from paper without errors.
GROUP_LENGTH: Final = 4
GROUPS: Final = 2
SEPARATOR: Final = "-"

#: No O/0, I/1, L or U. Every one of those is a transcription error waiting to
#: happen when the code is read off paper under stress.
ALPHABET: Final = "ABCDEFGHJKMNPQRSTVWXYZ23456789"

#: scrypt, not SHA-256. These are human-typed secrets that live for months, so
#: a stolen database table must not be brute-forceable at GPU speed. Parameters
#: are the interactive-login end of the scale: ~16 MiB and a few milliseconds.
_SCRYPT_N: Final = 2**14
_SCRYPT_R: Final = 8
_SCRYPT_P: Final = 1
_SALT_BYTES: Final = 16
_PREFIX: Final = "scrypt$"


class RecoveryCodeError(Exception):
    """Raised when a stored hash cannot be understood."""


def normalise(raw: str) -> str:
    """Fold a typed code into canonical form.

    Case, spaces and separators are all forgiven, because a person copying
    ``k7m2-pq4r`` from paper should not be refused over a dash. Ambiguous
    characters are mapped to the ones actually in the alphabet: someone who
    reads O for 0 must still get in.
    """
    text = (raw or "").strip().upper()
    for junk in (" ", "-", "_", ".", "\u200c"):
        text = text.replace(junk, "")
    return text.translate(
        # Two-argument form: the mapping overload is typed for int keys.
        str.maketrans("O0I1LU", "QQJ7JV")
    )


def _format(body: str) -> str:
    groups = [body[i : i + GROUP_LENGTH] for i in range(0, len(body), GROUP_LENGTH)]
    return SEPARATOR.join(groups)


def hash_code(code: str, *, salt: bytes | None = None) -> str:
    """Hash one code for storage. Format: ``scrypt$<hex salt>$<hex hash>``."""
    salt = salt or secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        normalise(code).encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"{_PREFIX}{salt.hex()}${digest.hex()}"


def _matches(code: str, stored: str) -> bool:
    if not stored.startswith(_PREFIX):
        raise RecoveryCodeError("Unrecognised recovery code hash format.")
    try:
        _, salt_hex, digest_hex = stored.split("$", 2)
        salt = bytes.fromhex(salt_hex)
    except ValueError as exc:
        raise RecoveryCodeError("Malformed recovery code hash.") from exc
    candidate = hashlib.scrypt(
        normalise(code).encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return hmac.compare_digest(candidate.hex(), digest_hex)


@dataclass(frozen=True, slots=True)
class IssuedCodes:
    """The result of generating a set.

    ``plaintext`` is shown to the administrator exactly once; ``hashes`` is what
    the database keeps. They are returned together, and separately, so that no
    caller can accidentally persist the plaintext by passing the wrong field.
    """

    plaintext: tuple[str, ...]
    hashes: tuple[str, ...]


def generate(count: int = CODE_COUNT) -> IssuedCodes:
    if count < 1:
        raise ValueError("At least one recovery code is required.")
    codes = []
    for _ in range(count):
        body = "".join(secrets.choice(ALPHABET) for _ in range(GROUP_LENGTH * GROUPS))
        codes.append(_format(body))
    return IssuedCodes(
        plaintext=tuple(codes),
        hashes=tuple(hash_code(code) for code in codes),
    )


@dataclass(frozen=True, slots=True)
class ConsumeResult:
    accepted: bool
    #: The hashes that remain valid. On acceptance the used one is gone: a
    #: recovery code that works twice is a password, and a weak one.
    remaining: tuple[str, ...]

    @property
    def remaining_count(self) -> int:
        return len(self.remaining)


def consume(stored_hashes: tuple[str, ...] | list[str], code: str) -> ConsumeResult:
    """Check a code against every stored hash and burn it on success.

    Every hash is checked even after a match is found. Returning early would
    make the response time reveal *which* code matched, and more importantly
    whether an early or late code was used.
    """
    normalised = normalise(code)
    if not normalised:
        return ConsumeResult(False, tuple(stored_hashes))

    matched_index: int | None = None
    for index, stored in enumerate(stored_hashes):
        if _matches(normalised, stored) and matched_index is None:
            matched_index = index
    if matched_index is None:
        return ConsumeResult(False, tuple(stored_hashes))
    remaining = tuple(h for i, h in enumerate(stored_hashes) if i != matched_index)
    return ConsumeResult(True, remaining)


def should_regenerate(remaining_count: int, *, floor: int = 3) -> bool:
    """Whether to nag the administrator to print a fresh set."""
    return remaining_count <= floor


EXHAUSTED_MESSAGE_FA: Final = "همهٔ کدهای بازیابی مصرف شده‌اند. مجموعهٔ تازه‌ای بسازید."
LOW_MESSAGE_FA: Final = "فقط {count} کد بازیابی باقی مانده است. مجموعهٔ تازه‌ای بسازید و چاپ کنید."

__all__ = [
    "ALPHABET",
    "CODE_COUNT",
    "EXHAUSTED_MESSAGE_FA",
    "LOW_MESSAGE_FA",
    "ConsumeResult",
    "IssuedCodes",
    "RecoveryCodeError",
    "consume",
    "generate",
    "hash_code",
    "normalise",
    "should_regenerate",
]
