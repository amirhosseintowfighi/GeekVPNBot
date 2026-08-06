"""JWT access tokens.

Choices, and why
----------------
* **HS256, not RS256.** One process signs and the same deployment verifies.
  Asymmetric keys buy nothing until a third party needs to verify offline, and
  they cost key distribution. Switching later means changing this file only.
* **Short TTL (default 15 minutes).** Access tokens are not revocable by
  design - checking a denylist on every request would put Redis in the hot path
  of every call. The short lifetime is what bounds the damage instead.
* **`iss` and `aud` are verified.** Without them, a token minted for the Mini
  App is happily accepted by the admin API.
* **Permissions are embedded.** Authorising a request touches no database.
* **`jti` on every token**, so a future denylist for the genuinely urgent case
  is a data change, not a redesign.

There is deliberately no `decode_unsafe` helper. The most common JWT
vulnerability in the wild is a developer reaching for one.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError, PyJWTError

from geekvpn.application.ports.tokens import AccessTokenClaims, IssuedToken
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.errors import TokenExpiredError, TokenInvalidError

TOKEN_TYPE_ACCESS: Final = "access"  # noqa: S105 - a claim value, not a secret
ALGORITHM: Final = "HS256"


class JwtAccessTokenService:
    def __init__(
        self,
        *,
        secret_key: str,
        issuer: str,
        audience: str,
        ttl: timedelta,
        leeway_seconds: int = 10,
    ) -> None:
        if len(secret_key) < 32:
            # A short HMAC key is a brute-forceable HMAC key.
            raise ValueError("JWT secret key must be at least 32 characters.")
        self._secret = secret_key
        self._issuer = issuer
        self._audience = audience
        self._ttl = ttl
        self._leeway = leeway_seconds

    def issue(
        self,
        *,
        subject_type: SubjectType,
        subject_id: uuid.UUID,
        session_id: uuid.UUID,
        role: str | None = None,
        permissions: Sequence[str] = (),
    ) -> IssuedToken:
        now = datetime.now(UTC)
        expires_at = now + self._ttl
        payload: dict[str, Any] = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": str(subject_id),
            "sid": str(session_id),
            "typ": TOKEN_TYPE_ACCESS,
            "styp": subject_type.value,
            "jti": str(uuid.uuid4()),
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        if role is not None:
            payload["role"] = role
        if permissions:
            payload["perms"] = list(permissions)

        token = jwt.encode(payload, self._secret, algorithm=ALGORITHM)
        return IssuedToken(value=token, expires_at=expires_at)

    def decode(self, token: str) -> AccessTokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],  # never trust the header's `alg`
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway,
                options={
                    "require": ["exp", "iat", "sub", "iss", "aud"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
        except ExpiredSignatureError as exc:
            raise TokenExpiredError() from exc
        except (InvalidTokenError, PyJWTError) as exc:
            raise TokenInvalidError() from exc

        if payload.get("typ") != TOKEN_TYPE_ACCESS:
            # A refresh token or any other artefact must never authorise a call.
            raise TokenInvalidError("Unexpected token type.")

        try:
            return AccessTokenClaims(
                subject_type=SubjectType(payload["styp"]),
                subject_id=uuid.UUID(payload["sub"]),
                session_id=uuid.UUID(payload["sid"]),
                issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
                expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
                token_id=uuid.UUID(payload["jti"]),
                role=payload.get("role"),
                permissions=tuple(payload.get("perms", ())),
            )
        except (KeyError, ValueError) as exc:
            raise TokenInvalidError("Malformed token claims.") from exc
