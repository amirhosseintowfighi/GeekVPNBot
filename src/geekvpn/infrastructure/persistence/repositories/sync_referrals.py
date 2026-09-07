"""The referral edge and the referral policy, on the synchronous side.

Wallets are synchronous and the edge has to be settled in the same transaction
as the credit, so this is a sync repository rather than a second call into the
async one. See `sync_scope.py` for why the two sides exist at all.

The policy is read here too, from the same settings rows the async
`PricingPolicyProvider` reads. Duplicated deliberately and narrowly: the async
provider cannot be awaited from an event subscriber, and copying six key names
is a smaller cost than a threadpool hop inside a payment transaction. The keys
are imported rather than retyped, so the two cannot drift apart silently.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from geekvpn.application.catalog.policy_provider import (
    KEY_REFERRAL_ENABLED,
    KEY_REFERRAL_FIRST_BPS,
    KEY_REFERRAL_INVITEE_BONUS,
    KEY_REFERRAL_MAX_PER_ORDER,
    KEY_REFERRAL_RECURRING_BPS,
    KEY_REFERRAL_SIGNUP_BONUS,
    PRICING_SETTING_DEFAULTS,
)
from geekvpn.application.payments.referral_rewards import ReferralEdge
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.rewards import ReferralPolicy
from geekvpn.infrastructure.persistence.models.provisioning import ReferralModel
from geekvpn.infrastructure.persistence.models.settings import SettingModel

_KEYS = (
    KEY_REFERRAL_ENABLED,
    KEY_REFERRAL_SIGNUP_BONUS,
    KEY_REFERRAL_FIRST_BPS,
    KEY_REFERRAL_RECURRING_BPS,
    KEY_REFERRAL_INVITEE_BONUS,
    KEY_REFERRAL_MAX_PER_ORDER,
)


class SyncReferralLedger:
    """Implements `ReferralLedger`. Never commits; the caller owns the transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def edge_for_invitee(self, invitee_telegram_id: int) -> ReferralEdge | None:
        row = self._session.execute(
            select(ReferralModel).where(ReferralModel.invitee_id == invitee_telegram_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        return ReferralEdge(
            referrer_telegram_id=row.referrer_id,
            invitee_telegram_id=row.invitee_id,
            converted_at=row.converted_at,
        )

    def settle(
        self,
        *,
        invitee_telegram_id: int,
        order_id: str,
        paid: int,
        reward: int,
        at: datetime,
    ) -> None:
        """Add this order to the edge.

        Revenue and reward accumulate; the conversion stamp is written once.
        An UPDATE with the column on both sides rather than a read-modify-
        write, so two orders settling at the same moment add up instead of one
        overwriting the other.
        """
        values: dict[str, object] = {
            "revenue_generated": ReferralModel.revenue_generated + paid,
            "reward_paid": ReferralModel.reward_paid + reward,
            "converted_at": _first_wins(ReferralModel.converted_at, at),
            "first_order_id": _first_wins(ReferralModel.first_order_id, order_id),
        }
        self._session.execute(
            update(ReferralModel)
            .where(ReferralModel.invitee_id == invitee_telegram_id)
            .values(**values)
        )
        self._session.flush()

    def policy(self) -> ReferralPolicy:
        """The live referral policy, defaults where nothing is stored."""
        rows = self._session.execute(
            select(SettingModel.key, SettingModel.value).where(SettingModel.key.in_(_KEYS))
        ).all()
        stored: dict[str, Any] = {row[0]: row[1] for row in rows}

        def read(key: str) -> object:
            return stored.get(key, PRICING_SETTING_DEFAULTS.get(key))

        return ReferralPolicy(
            enabled=bool(read(KEY_REFERRAL_ENABLED)),
            signup_bonus=_money(read(KEY_REFERRAL_SIGNUP_BONUS)) or Money.zero(),
            first_purchase_bps=_int(read(KEY_REFERRAL_FIRST_BPS)),
            recurring_bps=_int(read(KEY_REFERRAL_RECURRING_BPS)),
            invitee_bonus=_money(read(KEY_REFERRAL_INVITEE_BONUS)) or Money.zero(),
            max_reward_per_order=_money(read(KEY_REFERRAL_MAX_PER_ORDER)),
        )


def _first_wins(column: Any, value: object) -> Any:
    """`value` only where the column is still empty.

    The conversion stamp belongs to the first purchase. Overwriting it on
    every subsequent order would make "invited" and "converted" the same
    number on the operator's report, which is the one comparison the report
    exists to make.
    """
    return case((column.is_(None), value), else_=column)


def _int(value: object) -> int:
    """A stored setting, coerced. Anything unusable reads as zero.

    A malformed row must not throw inside a payment transaction: the purchase
    has already happened, and the worst honest answer is a reward of nothing.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip() or 0))
        except ValueError:
            return 0
    return 0


def _money(value: object) -> Money | None:
    amount = _int(value)
    return Money(amount) if amount > 0 else None


__all__ = ["SyncReferralLedger"]
