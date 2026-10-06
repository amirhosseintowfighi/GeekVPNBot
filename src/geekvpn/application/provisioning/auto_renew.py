"""Auto-renew from the wallet: when a service counts as "about to run out".

Two things built separately met here: the bot's per-service switch with its
worker job (`auto_renewal.AutoRenewal`), and the Android app's switch. They
are now one switch (`Subscription.auto_renew`) and one job, so a service
switched on in both places is renewed once, not twice. What the app's version
brought and the bot's lacked lives in this module: renewing when the traffic
is nearly gone, not only when the date is near, and the result vocabulary the
app shows next to the switch.
"""

from __future__ import annotations

import enum
from datetime import datetime, timedelta

#: Renew when this little time is left...
EXPIRY_WINDOW = timedelta(hours=24)
#: ...or this little traffic, whichever comes first.
TRAFFIC_FLOOR_FRACTION = 0.03
TRAFFIC_FLOOR_MIB = 100


class AutoRenewResult(enum.StrEnum):
    """What the last attempt came to, as the app shows it."""

    RENEWED = "renewed"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    #: The plan is archived or no longer on sale, or checkout refused it.
    UNAVAILABLE = "unavailable"
    #: Paid, but the panel has not delivered yet; the retry queue owns it now.
    PENDING = "pending"


def traffic_nearly_out(limit_mib: int | None, used_mib: int) -> bool:
    """Within 3% of the cap, or 100 MiB of it, whichever is more."""
    if limit_mib is None or limit_mib <= 0:
        return False
    return limit_mib - used_mib <= max(limit_mib * TRAFFIC_FLOOR_FRACTION, TRAFFIC_FLOOR_MIB)


def needs_renewal(
    *,
    expires_at: datetime,
    traffic_limit_mib: int | None,
    traffic_used_mib: int,
    now: datetime,
    window: timedelta = EXPIRY_WINDOW,
) -> bool:
    return expires_at - now <= window or traffic_nearly_out(traffic_limit_mib, traffic_used_mib)


__all__ = [
    "EXPIRY_WINDOW",
    "TRAFFIC_FLOOR_FRACTION",
    "TRAFFIC_FLOOR_MIB",
    "AutoRenewResult",
    "needs_renewal",
    "traffic_nearly_out",
]
