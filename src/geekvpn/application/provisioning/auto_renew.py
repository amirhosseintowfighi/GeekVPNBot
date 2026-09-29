"""Auto-renew from the wallet: when a service is about to run out.

The customer switches it on per service in the Android app. The worker buys
the same plan again from the wallet, as a renewal of that service, shortly
before it expires or when its traffic is nearly gone. A renewal that fails
(not enough balance, the plan is no longer sold) is not retried until
:data:`RETRY_AFTER` has passed, and the reason is kept for the app to show.

Only the platform's own services: a reseller's customer pays that shop, and
its wallet and prices are the reseller's business.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta

#: Renew when this little time is left...
EXPIRY_WINDOW = timedelta(hours=24)
#: ...or this little traffic, whichever comes first.
TRAFFIC_FLOOR_FRACTION = 0.03
TRAFFIC_FLOOR_MIB = 100
#: After a failed attempt, wait this long before the next one.
RETRY_AFTER = timedelta(hours=12)


class AutoRenewResult(enum.StrEnum):
    RENEWED = "renewed"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    #: The plan is archived or no longer on sale, or checkout refused it.
    UNAVAILABLE = "unavailable"
    #: Paid, but the panel has not delivered yet; the retry queue owns it now.
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class RenewalCandidate:
    subscription_id: str
    telegram_id: int
    plan_id: str | None
    expires_at: datetime
    traffic_limit_mib: int | None
    traffic_used_mib: int
    last_attempt_at: datetime | None


def is_due(candidate: RenewalCandidate, now: datetime) -> bool:
    if candidate.plan_id is None:
        return False
    if candidate.last_attempt_at is not None and now - candidate.last_attempt_at < RETRY_AFTER:
        return False
    if candidate.expires_at - now <= EXPIRY_WINDOW:
        return True
    limit = candidate.traffic_limit_mib
    if limit is None or limit <= 0:
        return False
    left = limit - candidate.traffic_used_mib
    return left <= max(limit * TRAFFIC_FLOOR_FRACTION, TRAFFIC_FLOOR_MIB)


__all__ = [
    "EXPIRY_WINDOW",
    "RETRY_AFTER",
    "AutoRenewResult",
    "RenewalCandidate",
    "is_due",
]
