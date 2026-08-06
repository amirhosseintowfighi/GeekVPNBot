"""Password hashing port."""

from __future__ import annotations

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
