"""States a reseller account can be in."""

from __future__ import annotations

import enum


class ResellerStatus(enum.StrEnum):
    ACTIVE = "active"
    #: Cannot provision, and their bot answers that sales are paused. Their
    #: existing customers keep working: suspending a reseller must never take
    #: a service away from somebody who paid for it.
    SUSPENDED = "suspended"
    #: Closed for good. Kept rather than deleted, because their subscriptions
    #: and ledger entries still point here.
    CLOSED = "closed"

    @property
    def may_provision(self) -> bool:
        return self is ResellerStatus.ACTIVE


__all__ = ["ResellerStatus"]
