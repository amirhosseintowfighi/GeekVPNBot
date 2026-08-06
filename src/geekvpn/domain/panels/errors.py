"""Panel failure taxonomy.

The distinction that matters operationally is **retryable vs terminal**, and
above that, **whose fault it is**. A saga that cannot tell "the panel is down"
from "you asked for something impossible" will either retry forever or refund a
customer who could have been served.

Every adapter MUST translate its transport errors into these. A raw
`httpx.HTTPError` escaping an adapter is a bug, and `test_contract.py`
asserts it cannot happen.
"""

from __future__ import annotations

from typing import Any

from geekvpn.domain.base.errors import DomainError


class PanelError(DomainError):
    """Base for every panel-integration failure."""

    code = "panel_error"
    message = "The VPN panel could not complete the request."

    #: Whether an identical retry could plausibly succeed later.
    retryable: bool = False

    def __init__(
        self, message: str | None = None, *, panel: str | None = None, **details: Any
    ) -> None:
        self.panel = panel
        super().__init__(message, panel=panel, **details)


class PanelUnreachable(PanelError):
    """Network failure, timeout, DNS, TLS, or a 5xx.

    Retryable: the request may never have been seen by the panel. Callers must
    pair the retry with an idempotency key, because "timed out" does not mean
    "did not happen".
    """

    code = "panel_unreachable"
    message = "The VPN panel is not responding."
    retryable = True


class PanelRateLimited(PanelError):
    """The panel asked us to slow down (429)."""

    code = "panel_rate_limited"
    message = "The VPN panel is rate limiting us."
    retryable = True

    def __init__(
        self,
        message: str | None = None,
        *,
        retry_after_seconds: int | None = None,
        **kw: Any,
    ) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message, retry_after_seconds=retry_after_seconds, **kw)


class PanelAuthFailed(PanelError):
    """Our stored credentials were rejected (401/403).

    NOT retryable: hammering a panel with bad credentials gets our IP banned.
    This should page a human - it usually means someone rotated the panel
    password without updating the platform.
    """

    code = "panel_auth_failed"
    message = "The VPN panel rejected our credentials."
    retryable = False


class AccountNotFound(PanelError):
    code = "panel_account_not_found"
    message = "No such account exists on the VPN panel."
    retryable = False


class AccountAlreadyExists(PanelError):
    """Username collision.

    Frequently benign: it is what a retried create looks like after the first
    attempt actually succeeded but the response was lost. Provisioning treats
    this as a signal to re-read rather than to fail.
    """

    code = "panel_account_exists"
    message = "That account already exists on the VPN panel."
    retryable = False


class QuotaExceeded(PanelError):
    """The panel or node refused for capacity reasons."""

    code = "panel_quota_exceeded"
    message = "The VPN panel has no capacity for this account."
    retryable = False


class CapabilityNotSupported(PanelError):
    """Asked an adapter for something it never claimed to do.

    This is a programming error, not an operational one: the caller should have
    checked `adapter.capabilities` first.
    """

    code = "panel_capability_unsupported"
    message = "This VPN panel does not support that operation."
    retryable = False


class PanelContractViolation(PanelError):
    """The panel returned something we cannot parse.

    Almost always means the panel was upgraded and changed its response shape.
    Surfaced loudly and separately from a transport error so that a panel
    upgrade is diagnosable in one glance at the logs.
    """

    code = "panel_contract_violation"
    message = "The VPN panel returned an unexpected response."
    retryable = False
