"""What happens when a reseller's balance goes under.

This platform has no credit limit in the usual sense - no agreed ceiling, no
settlement date, no number anybody keeps up to date. What it has instead is a
consequence: a reseller whose balance is negative has their customers' services
suspended, and they come back the moment the balance is positive again.

That is a better enforcement mechanism than a refusal, because it applies to a
debt that already exists rather than only to the next purchase, and it gives
the reseller exactly one thing to do about it.

Three properties this has to hold, and each is a way to get it wrong:

* **Only the reseller's own customers.** A platform-sold subscription has no
  reseller and must never be caught by this.
* **Idempotent.** It runs after every balance change, and suspending an
  already-suspended account is a wasted panel call at best.
* **Suspension by *this*, not suspension in general.** A subscription an
  operator suspended for abuse must not come back when an unrelated balance is
  topped up, so the reason is what tells the two apart.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import structlog

from geekvpn.domain.provisioning.enums import SubscriptionState

logger = structlog.stdlib.get_logger(__name__)

#: Written onto every subscription this suspends, and matched on the way back.
#:
#: The marker is the whole mechanism for telling "off because the reseller owes
#: us money" apart from "off because an operator turned it off". Without it, a
#: top-up would resume a subscription somebody had deliberately stopped.
ARREARS_REASON_FA = "بدهی نماینده — سرویس تا تسویه‌ی حساب غیرفعال است"


class SubscriptionAccess(Protocol):
    """The two operations, as the admin service already spells them."""

    async def suspend(self, subscription_id: str, *, reason_fa: str) -> object: ...

    async def resume(self, subscription_id: str) -> object: ...


class SuspendableSubscription(Protocol):
    """The three fields this reads, and nothing else about a subscription."""

    id: str

    @property
    def state(self) -> SubscriptionState: ...

    suspend_reason_fa: str | None


class ResellerSubscriptions(Protocol):
    async def list_for_reseller(
        self, reseller_id: uuid.UUID
    ) -> Sequence[SuspendableSubscription]: ...


@dataclass(frozen=True, slots=True)
class ArrearsOutcome:
    suspended: int = 0
    resumed: int = 0
    failed: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.suspended or self.resumed)


class ArrearsEnforcer:
    def __init__(
        self, *, subscriptions: ResellerSubscriptions, access: SubscriptionAccess
    ) -> None:
        self._subscriptions = subscriptions
        self._access = access

    async def apply(self, *, reseller_id: uuid.UUID, in_arrears: bool) -> ArrearsOutcome:
        """Bring this reseller's customers in line with their balance.

        Every panel call is allowed to fail on its own. A node that is down
        must not stop the other twenty from being suspended, and must not turn
        a balance adjustment into a five-hundred error for the operator who
        made it - so failures are counted and logged, and the next call to this
        will pick them up, because the state it reads is the truth.
        """
        rows = await self._subscriptions.list_for_reseller(reseller_id)
        suspended = resumed = failed = 0

        for subscription in rows:
            state = subscription.state

            if in_arrears and state is SubscriptionState.ACTIVE:
                try:
                    await self._access.suspend(
                        subscription.id, reason_fa=ARREARS_REASON_FA
                    )
                    suspended += 1
                except Exception:
                    failed += 1
                    logger.info(
                        "reseller.arrears.suspend_failed", subscription_id=subscription.id
                    )
            elif (
                not in_arrears
                and state is SubscriptionState.SUSPENDED
                # Only what this suspended. An operator who stopped a
                # subscription for abuse did not stop it over money, and a
                # top-up must not undo their decision.
                and subscription.suspend_reason_fa == ARREARS_REASON_FA
            ):
                try:
                    await self._access.resume(subscription.id)
                    resumed += 1
                except Exception:
                    failed += 1
                    logger.info(
                        "reseller.arrears.resume_failed", subscription_id=subscription.id
                    )

        if suspended or resumed or failed:
            logger.info(
                "reseller.arrears.applied",
                reseller_id=str(reseller_id),
                in_arrears=in_arrears,
                suspended=suspended,
                resumed=resumed,
                failed=failed,
            )
        return ArrearsOutcome(suspended=suspended, resumed=resumed, failed=failed)


__all__ = ["ARREARS_REASON_FA", "ArrearsEnforcer", "ArrearsOutcome"]
