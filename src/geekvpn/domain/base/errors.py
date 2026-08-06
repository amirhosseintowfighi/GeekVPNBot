"""Domain error taxonomy.

Every layer above maps these onto its own transport:
HTTP problem details in the API, a Persian message in the bot.
Domain code never knows about status codes.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for every expected, business-meaningful failure.

    Unexpected failures (bugs, infrastructure outages) must NOT subclass this;
    they propagate and are reported as 500s.
    """

    code: str = "domain_error"
    message: str = "A domain error occurred."

    def __init__(self, message: str | None = None, **details: Any) -> None:
        self.message = message or self.message
        self.details: dict[str, Any] = details
        super().__init__(self.message)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, message={self.message!r})"


class ValidationError(DomainError):
    code = "validation_error"
    message = "The provided data is invalid."


class NotFoundError(DomainError):
    code = "not_found"
    message = "The requested resource was not found."


class ConflictError(DomainError):
    code = "conflict"
    message = "The operation conflicts with the current state."


class AuthenticationError(DomainError):
    """The caller could not be identified. Maps to HTTP 401.

    Distinct from `PermissionDeniedError`: 401 means "we do not know who you
    are", 403 means "we know exactly who you are and the answer is no".
    Conflating them makes clients retry logins they should not.
    """

    code = "unauthenticated"
    message = "Authentication is required."


class PermissionDeniedError(DomainError):
    code = "permission_denied"
    message = "You are not allowed to perform this action."


class RateLimitedError(DomainError):
    code = "rate_limited"
    message = "Too many requests. Please try again shortly."
