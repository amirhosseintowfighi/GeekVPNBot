"""The bot's ``TrialService``: the same `FreeTrial` the Mini App calls.

Nothing is reimplemented. The claim, the zero-priced paid orders and the
provisioning are `FreeTrial`'s; this adapter only commits between placing and
delivering - the same boundary the Mini App endpoint keeps - and turns what
came up into cards the bot already knows how to show.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.application.bot.read_models import TrialClaimCard, TrialOfferCard
from geekvpn.application.platform.settings_service import (
    TRIAL_AFTER_MESSAGE_FA,
    TRIAL_INTRO_FA,
    SettingsService,
)
from geekvpn.application.provisioning.free_trial import FreeTrial
from geekvpn.domain.provisioning.errors import FreeTrialUnavailable
from geekvpn.infrastructure.bot.readers import to_card


class BotTrialAdapter:
    """Implements ``application.bot.ports.TrialService``."""

    def __init__(
        self,
        *,
        trial: FreeTrial,
        settings: SettingsService,
        session: AsyncSession,
        telegram_id: Callable[[uuid.UUID], Awaitable[int | None]],
    ) -> None:
        self._trial = trial
        self._settings = settings
        self._session = session
        self._telegram_id = telegram_id

    async def offer(self, user_id: uuid.UUID) -> TrialOfferCard:
        telegram_id = await self._telegram_id(user_id)
        if telegram_id is None:
            return TrialOfferCard(available=False, traffic_mib=0, duration_days=0)
        offer = await self._trial.offer(telegram_id)
        return TrialOfferCard(
            available=offer.available,
            traffic_mib=offer.traffic_mib,
            duration_days=offer.duration_days,
            intro_fa=await self._settings.get(TRIAL_INTRO_FA),
        )

    async def claim(self, user_id: uuid.UUID) -> TrialClaimCard:
        telegram_id = await self._telegram_id(user_id)
        if telegram_id is None:
            raise FreeTrialUnavailable("No customer to give the trial to.")
        orders = await self._trial.place(telegram_id)
        # Once the claim and its paid orders are stored the trial is owed, and
        # a panel that fails afterwards leaves them to the retry queue instead
        # of losing the claim.
        await self._session.commit()
        delivery = await self._trial.deliver(orders)
        await self._session.commit()

        by_id = {order.id: order for order in orders}
        cards = tuple(
            to_card(subscription, by_id.get(subscription.order_id or ""))
            for subscription in delivery.subscriptions
        )
        return TrialClaimCard(
            cards=cards,
            pending=delivery.pending,
            after_message_fa=await self._settings.get(TRIAL_AFTER_MESSAGE_FA),
        )


__all__ = ["BotTrialAdapter"]
