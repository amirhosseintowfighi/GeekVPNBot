"""Correlation id propagation.

One id follows a request from Nginx through the API, the outbox, the worker and
the panel adapter. Without it, debugging a failed provisioning across four
processes is guesswork.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

CORRELATION_ID_HEADER = "X-Request-ID"

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def bind_correlation_id(value: str | None = None) -> Token[str | None]:
    """Bind an id to the current context and return a token for resetting it."""
    return _correlation_id.set(value or new_correlation_id())


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def reset_correlation_id(token: Token[str | None]) -> None:
    _correlation_id.reset(token)
