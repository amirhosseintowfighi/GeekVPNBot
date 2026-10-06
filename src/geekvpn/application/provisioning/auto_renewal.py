"""Renewing a service from the customer's wallet before it runs out.

Only for services whose owner switched it on. The bot's renewal flow is
two taps on purpose - the customer sees the invoice before paying - and this
does not replace it; it is the customer choosing, once, to skip those taps.

Each expiry is attempted once. A wallet that cannot cover the renewal is told
so a single time for that expiry, not on every tick until the service dies:
the attempt key is the subscription and the date it runs out, so a manual
renewal (which moves the date) makes it eligible again next time.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from geekvpn.application.ports.clock import Clock
from geekvpn.application.provisioning.auto_renew import EXPIRY_WINDOW, needs_renewal
from geekvpn.domain.notifications.message import RenderedMessage, fa_digits, fa_toman, render
from geekvpn.domain.provisioning.subscription import Subscription

_log = logging.getLogger(__name__)

#: How long before the end a renewal is attempted. A day, so a wallet that
#: is short still leaves the customer time to top up before they are cut off.
#: A service nearly out of traffic is renewed too, whatever its date.
AUTO_RENEW_WINDOW = EXPIRY_WINDOW


class RenewalOutcome(StrEnum):
    RENEWED = "renewed"
    #: The wallet could not cover it. Nothing was charged.
    SHORT = "short"
    #: No plan to renew onto (retired, or an adopted account with none).
    NOT_RENEWABLE = "not_renewable"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ChargeResult:
    outcome: RenewalOutcome
    #: What was charged, or what was missing when `SHORT`. In Toman, like `Money`.
    amount: int = 0


class AutoRenewCandidates(Protocol):
    async def list_auto_renew_due(
        self, *, before: datetime, limit: int = 200
    ) -> Sequence[Subscription]:
        """Usable subscriptions with auto-renew on that end before ``before``,
        or are nearly out of traffic."""
        ...


class AttemptLog(Protocol):
    async def seen(self, key: str) -> bool: ...

    async def mark(self, key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class AutoRenewReport:
    examined: int = 0
    renewed: int = 0
    short: int = 0
    failed: int = 0


class AutoRenewal:
    def __init__(
        self,
        *,
        candidates: AutoRenewCandidates,
        charge: Callable[[Subscription], Awaitable[ChargeResult]],
        attempts: AttemptLog,
        notify: Callable[[Subscription, RenderedMessage], Awaitable[None]],
        enabled: Callable[[], Awaitable[bool]],
        clock: Clock,
        window: timedelta = AUTO_RENEW_WINDOW,
    ) -> None:
        self._candidates = candidates
        self._charge = charge
        self._attempts = attempts
        self._notify = notify
        self._enabled = enabled
        self._clock = clock
        self._window = window

    async def run(self) -> AutoRenewReport:
        # The operator's switch. Off, and nobody's wallet is touched even if
        # they opted in - which is what an operator reaching for it means.
        if not await self._enabled():
            return AutoRenewReport()

        now = self._clock.now()
        examined = renewed = short = failed = 0
        for subscription in await self._candidates.list_auto_renew_due(before=now + self._window):
            if not needs_renewal(
                expires_at=subscription.expires_at,
                traffic_limit_mib=subscription.traffic_limit_mib,
                traffic_used_mib=subscription.traffic_used_mib,
                now=now,
                window=self._window,
            ):
                continue
            examined += 1
            key = attempt_key(subscription)
            if await self._attempts.seen(key):
                continue
            try:
                result = await self._charge(subscription)
            except Exception:
                _log.exception("auto_renew.charge_crashed subscription=%s", subscription.id)
                result = ChargeResult(RenewalOutcome.FAILED)
            # Marked whatever happened: a renewal that failed is retried by the
            # customer or an operator, not by a loop that may charge twice.
            await self._attempts.mark(key)

            if result.outcome is RenewalOutcome.RENEWED:
                renewed += 1
                message = render(
                    "renewal.auto_done", plan=_name(subscription), amount=fa_toman(result.amount)
                )
            elif result.outcome is RenewalOutcome.SHORT:
                short += 1
                message = render(
                    "renewal.auto_short",
                    plan=_name(subscription),
                    amount=fa_toman(result.amount),
                    hours=fa_digits(int(self._window.total_seconds() // 3600)),
                )
            else:
                failed += 1
                message = render("renewal.auto_failed", plan=_name(subscription))
            try:
                await self._notify(subscription, message)
            except Exception:
                _log.exception("auto_renew.notify_failed subscription=%s", subscription.id)
        return AutoRenewReport(examined=examined, renewed=renewed, short=short, failed=failed)


def attempt_key(subscription: Subscription) -> str:
    """One attempt per expiry date: a renewal moves the date, which makes the
    service eligible again for its next run-out, and a failed one waits for
    the customer or an operator rather than a loop that might charge twice."""
    return f"{subscription.id}:{subscription.expires_at.isoformat()}"


def _name(subscription: Subscription) -> str:
    return subscription.display_name or subscription.remote_username


__all__ = [
    "AUTO_RENEW_WINDOW",
    "AttemptLog",
    "AutoRenewCandidates",
    "AutoRenewReport",
    "AutoRenewal",
    "ChargeResult",
    "RenewalOutcome",
    "attempt_key",
]
