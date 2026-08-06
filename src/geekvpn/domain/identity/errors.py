"""Identity failures.

Note what is deliberately *not* here: no error distinguishes "unknown admin"
from "wrong password". Both raise `InvalidCredentialsError` with the same
message, because a login endpoint that leaks account existence is an account
enumeration oracle.
"""

from __future__ import annotations

from geekvpn.domain.base.errors import (
    AuthenticationError,
    ConflictError,
    PermissionDeniedError,
)


class InvalidCredentialsError(AuthenticationError):
    code = "invalid_credentials"
    message = "Invalid credentials."


class InvalidTelegramAuthError(AuthenticationError):
    code = "invalid_telegram_auth"
    message = "Telegram authentication data is invalid or has expired."


class TokenInvalidError(AuthenticationError):
    code = "token_invalid"
    message = "The token is invalid."


class TokenExpiredError(AuthenticationError):
    code = "token_expired"
    message = "The token has expired."


class SessionRevokedError(AuthenticationError):
    code = "session_revoked"
    message = "This session is no longer valid. Please sign in again."


class TokenReuseDetectedError(AuthenticationError):
    """A refresh token was presented twice.

    Either the token was stolen, or a client has a bug. Both are handled the
    same way: the entire session family is destroyed immediately.
    """

    code = "token_reuse_detected"
    message = "Security alert: this session has been terminated. Please sign in again."


class TwoFactorRequiredError(AuthenticationError):
    code = "two_factor_required"
    message = "A two-factor authentication code is required."


class TwoFactorInvalidError(AuthenticationError):
    code = "two_factor_invalid"
    message = "The two-factor code is invalid."


class AccountSuspendedError(PermissionDeniedError):
    code = "account_suspended"
    message = "This account is suspended."


class AccountLockedError(AuthenticationError):
    code = "account_locked"
    message = "Too many failed attempts. This account is temporarily locked."


class IpNotAllowedError(PermissionDeniedError):
    code = "ip_not_allowed"
    message = "Access from this network is not permitted."


class MissingPermissionError(PermissionDeniedError):
    code = "missing_permission"
    message = "You do not have permission to perform this action."


class AdminAlreadyExistsError(ConflictError):
    code = "admin_already_exists"
    message = "An administrator with these details already exists."
