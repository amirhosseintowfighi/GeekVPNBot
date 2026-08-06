"""Access-token port.

The application knows there is *a* token service. It does not know it is JWT,
and nothing outside `infrastructure.security` imports PyJWT.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from geekvpn.domain.identity.enums import SubjectType


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """The verified content of an access token."""

    subject_type: SubjectType
    subject_id: uuid.UUID
    session_id: uuid.UUID
    issued_at: datetime
    expires_at: datetime
    token_id: uuid.UUID
    role: str | None = None
    permissions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IssuedToken:
    value: str
    expires_at: datetime


@runtime_checkable
class AccessTokenService(Protocol):
    def issue(
        self,
        *,
        subject_type: SubjectType,
        subject_id: uuid.UUID,
        session_id: uuid.UUID,
        role: str | None = None,
        permissions: Sequence[str] = (),
    ) -> IssuedToken:
        """Mint a short-lived access token."""
        ...

    def decode(self, token: str) -> AccessTokenClaims:
        """Verify signature, issuer, audience and expiry.

        Raises `TokenExpiredError` or `TokenInvalidError`. Never returns an
        unverified payload - there is deliberately no `decode_unsafe`.
        """
        ...


@runtime_checkable
class RefreshTokenFactory(Protocol):
    def generate(self) -> tuple[str, str]:
        """Return `(plaintext, hash)`. Only the hash is ever persisted."""
        ...

    def hash(self, plaintext: str) -> str: ...
