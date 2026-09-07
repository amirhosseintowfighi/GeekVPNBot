"""Password, TOTP and recovery-code ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password: str, password_hash: str) -> bool:
        """Constant-time verification. Returns False rather than raising."""
        ...

    def needs_rehash(self, password_hash: str) -> bool:
        """True when the hash uses outdated parameters and should be upgraded."""
        ...


@runtime_checkable
class TotpService(Protocol):
    def generate_secret(self) -> str: ...

    def provisioning_uri(self, *, secret: str, account: str, issuer: str) -> str: ...

    def verify(self, *, secret: str, code: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    accepted: bool
    #: What survives. On acceptance the used hash is gone - a recovery code
    #: that works twice is a password, and a weak one.
    remaining: tuple[str, ...]


@runtime_checkable
class RecoveryCodes(Protocol):
    """Single-use codes for an administrator whose TOTP device is gone.

    A port rather than a direct call, because the checking is scrypt and the
    application layer does not hash - the same reason `PasswordHasher` exists.
    """

    def issue(self, count: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """A fresh set: the codes to show once, and the hashes to store."""
        ...

    def consume(self, hashes: tuple[str, ...], code: str) -> RecoveryOutcome: ...
