"""The referral edge.

One row per invited customer, written once when they register. The table had
five readers and no writer: the customer's own referral screen, the operator's
programme report and three analytics queries all counted rows nothing ever
inserted, so a link that worked perfectly answered "nobody has used it yet".

Not shop-scoped. The edge is between two Telegram accounts, and the invitee
column is unique platform-wide - which is deliberate: somebody who arrived on
one person's link did not arrive on anybody else's, whichever bot they opened.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.infrastructure.persistence.models.provisioning import ReferralModel


class SqlAlchemyReferralRepository:
    """Writes the edge. Never commits; the unit of work owns the transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_signup(
        self,
        *,
        referral_id: str,
        referrer_telegram_id: int,
        invitee_telegram_id: int,
        code: str,
        joined_at: datetime,
    ) -> bool:
        """Record the edge. `False` if there was already one, or it is a loop.

        Checked rather than left to the unique constraint. A duplicate insert
        would abort the transaction the customer is being *registered* in, so
        the second tap of a shared link would cost them their account rather
        than their bonus.
        """
        if referrer_telegram_id == invitee_telegram_id:
            return False
        existing = await self._session.execute(
            select(ReferralModel.id).where(
                ReferralModel.invitee_id == invitee_telegram_id
            )
        )
        if existing.scalar_one_or_none() is not None:
            return False

        self._session.add(
            ReferralModel(
                id=referral_id,
                referrer_id=referrer_telegram_id,
                invitee_id=invitee_telegram_id,
                code=code,
                joined_at=joined_at,
            )
        )
        await self._session.flush()
        return True


__all__ = ["SqlAlchemyReferralRepository"]
