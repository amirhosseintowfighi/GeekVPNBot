"""Deleting the panel accounts of services that ended long enough ago.

A panel keeps every account anyone ever bought until somebody deletes it,
and an x-ui inbound with thousands of dead clients is slow to read and slow
to edit. The operator chooses how long a lapsed service is kept - long
enough for a customer to renew it and keep the same link - and this removes
what is older.

Revoked, not erased: the subscription row stays, because orders, payments
and refunds point at it. Only the account on the panel goes.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from typing import Protocol

from geekvpn.application.ports.clock import Clock
from geekvpn.domain.provisioning.subscription import Subscription

_log = logging.getLogger(__name__)

CLEANUP_REASON_FA = "حذف خودکار پس از انقضا"


class LapsedServices(Protocol):
    async def list_lapsed_before(
        self, *, cutoff: datetime, limit: int = 200
    ) -> Sequence[Subscription]: ...


class ExpiredCleanup:
    def __init__(
        self,
        *,
        lapsed: LapsedServices,
        revoke: Callable[[str, str], Awaitable[object]],
        hours: Callable[[], Awaitable[int]],
        clock: Clock,
    ) -> None:
        self._lapsed = lapsed
        self._revoke = revoke
        self._hours = hours
        self._clock = clock

    async def run(self) -> list[Subscription]:
        """Revoke every service past the grace period. Returns the ones removed."""
        hours = await self._hours()
        if hours <= 0:
            return []
        cutoff = self._clock.now() - timedelta(hours=hours)
        removed: list[Subscription] = []
        for subscription in await self._lapsed.list_lapsed_before(cutoff=cutoff):
            try:
                await self._revoke(subscription.id, CLEANUP_REASON_FA)
            except Exception:
                # A panel that will not answer keeps its account until the next
                # run; the rest of the batch still goes.
                _log.exception("cleanup.revoke_failed subscription=%s", subscription.id)
                continue
            removed.append(subscription)
        return removed


__all__ = ["CLEANUP_REASON_FA", "ExpiredCleanup", "LapsedServices"]
