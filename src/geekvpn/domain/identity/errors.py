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
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
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


# -- app sign-in (AppLinkLogin) ------------------------------------------------


class AppLoginNotFoundError(NotFoundError):
    """No request behind this code or poll token.

    Also what a guessed or mistyped value gets: a reply that told "never
    existed" apart from "already used" would let somebody probe for codes.
    """

    code = "app_login_not_found"
    message = "This sign-in request does not exist."


class AppLoginExpiredError(ConflictError):
    code = "app_login_expired"
    message = "This sign-in request has expired."


class AppLoginAlreadyUsedError(ConflictError):
    """The link was already opened, or the request was already decided.

    One link, one Telegram account, one decision: a forwarded link that a
    second person opens must not give them a button that signs the first
    person's phone into their account.
    """

    code = "app_login_already_used"
    message = "This sign-in request has already been used."


class AppLoginNotYoursError(PermissionDeniedError):
    code = "app_login_not_yours"
    message = "This sign-in request belongs to someone else."


class AppUsernameInvalidError(ValidationError):
    code = "app_username_invalid"
    message = "The username must be 4-32 letters, digits or underscores, starting with a letter."


class AppUsernameTakenError(ConflictError):
    code = "app_username_taken"
    message = "This username is already taken."


class AppPasswordWeakError(ValidationError):
    code = "app_password_weak"
    message = "The password must be 8-128 characters and must not be the username."
