"""The bot's ``ServiceOwnership``: auto-renew, rename and transfer.

The service is looked up among the customer's *own* services rather than by
id, so a forged callback cannot reach anybody else's. Every change is a
method on the `Subscription` aggregate; this adapter only finds, saves and
tells people.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.application.bot.read_models import OwnerOptions, SubscriptionCard
from geekvpn.application.notifications.operator_alerts import AlertKind
from geekvpn.application.platform.settings_service import (
    AUTO_RENEW_ENABLED,
    RENAME_ENABLED,
    TRANSFER_ENABLED,
    SettingsService,
)
from geekvpn.domain.notifications.message import render
from geekvpn.domain.provisioning.subscription import Subscription
from geekvpn.infrastructure.bot.readers import to_card
from geekvpn.infrastructure.bot.sync_readers import SyncBridge
from geekvpn.infrastructure.di.sync_scope import SyncScope
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.infrastructure.persistence.repositories.provisioning import (
    SqlAlchemyOrderRepository,
    SqlAlchemySubscriptionRepository,
)
from geekvpn.infrastructure.persistence.repositories.user import SqlAlchemyUserRepository

logger = get_logger("bot.ownership")

#: Operator reports. Beside the adapter that sends them, like the receipt
#: alert's copy: infrastructure may not import the bot's text module.
TRANSFER_REPORT_FA = (
    "🔄 <b>انتقال سرویس</b>\n\n"
    "سرویس: <code>{username}</code>\n"
    "از: <code>{from_id}</code>\n"
    "به: <code>{to_id}</code>"
)
RENAME_REPORT_FA = (
    "✏️ <b>تغییر نام سرویس</b>\n\n"
    "کاربر: <code>{user_id}</code>\n"
    "سرویس: <code>{username}</code>\n"
    "نام جدید: {name}"
)


class ServiceDisabled(PermissionError):
    """The shop switched this control off after the button was drawn."""


class BotServiceOwnership:
    """Implements ``application.bot.ports.ServiceOwnership``."""

    def __init__(
        self,
        *,
        users: SqlAlchemyUserRepository,
        subscriptions: SqlAlchemySubscriptionRepository,
        orders: SqlAlchemyOrderRepository,
        session: AsyncSession,
        settings: SettingsService,
        bridge: SyncBridge,
        reseller_id: uuid.UUID | None,
    ) -> None:
        self._users = users
        self._subscriptions = subscriptions
        self._orders = orders
        self._session = session
        self._settings = settings
        self._bridge = bridge
        self._reseller_id = reseller_id

    async def options(self) -> OwnerOptions:
        return OwnerOptions(
            auto_renew=await self._settings.get(AUTO_RENEW_ENABLED),
            rename=await self._settings.get(RENAME_ENABLED),
            transfer=await self._settings.get(TRANSFER_ENABLED),
        )

    async def set_auto_renew(
        self, user_id: uuid.UUID, subscription_id: uuid.UUID, *, enabled: bool
    ) -> SubscriptionCard:
        if enabled and not await self._settings.get(AUTO_RENEW_ENABLED):
            raise ServiceDisabled("Auto-renewal is switched off.")
        subscription = await self._own(user_id, subscription_id)
        subscription.set_auto_renew(enabled)
        return await self._save(subscription)

    async def rename(
        self, user_id: uuid.UUID, subscription_id: uuid.UUID, *, name: str | None
    ) -> SubscriptionCard:
        if not await self._settings.get(RENAME_ENABLED):
            raise ServiceDisabled("Renaming is switched off.")
        subscription = await self._own(user_id, subscription_id)
        subscription.rename(name)
        card = await self._save(subscription)
        await self._report(
            RENAME_REPORT_FA.format(
                user_id=subscription.user_id,
                username=subscription.remote_username,
                name=_escape(subscription.display_name or "—"),
            )
        )
        return card

    async def transfer(
        self, user_id: uuid.UUID, subscription_id: uuid.UUID, *, to_telegram_id: int
    ) -> None:
        if not await self._settings.get(TRANSFER_ENABLED):
            raise ServiceDisabled("Transfers are switched off.")
        subscription = await self._own(user_id, subscription_id)
        # A customer of this shop, not merely somebody on Telegram: a service
        # handed to a stranger who never started the bot would belong to
        # nobody who could see it, and one handed across shops would move a
        # reseller's customer into our books.
        recipient = await self._users.get_by_telegram_id(
            to_telegram_id, reseller_id=self._reseller_id
        )
        if recipient is None:
            raise LookupError(f"No customer {to_telegram_id} in this shop.")
        previous = subscription.user_id
        subscription.transfer_to(recipient.telegram_id)
        await self._subscriptions.update(subscription)
        await self._session.commit()

        name = subscription.display_name or subscription.remote_username
        message = render("subscription.transferred_in", plan=name)

        def tell_recipient(scope: SyncScope) -> None:
            scope.engine.dispatch(
                user_id=recipient.telegram_id, message=message, source="subscription.transfer"
            )

        try:
            await self._bridge.run(tell_recipient)
        except Exception:
            logger.exception("ownership.recipient_not_told", subscription=subscription.id)
        await self._report(
            TRANSFER_REPORT_FA.format(
                username=subscription.remote_username, from_id=previous, to_id=to_telegram_id
            )
        )

    async def _own(self, user_id: uuid.UUID, subscription_id: uuid.UUID) -> Subscription:
        user = await self._users.get(user_id)
        if user is None:
            raise LookupError(f"No user {user_id}.")
        for subscription in await self._subscriptions.list_for_user(user.telegram_id):
            if _same(subscription.id, subscription_id):
                return subscription
        raise LookupError(f"No subscription {subscription_id} for this customer.")

    async def _save(self, subscription: Subscription) -> SubscriptionCard:
        await self._subscriptions.update(subscription)
        await self._session.commit()
        order = await self._orders.get(subscription.order_id) if subscription.order_id else None
        return to_card(subscription, order)

    async def _report(self, text: str) -> None:
        def work(scope: SyncScope) -> None:
            scope.operator_reports.send(AlertKind.REPORT, text)

        try:
            await self._bridge.run(work)
        except Exception:
            logger.exception("ownership.report_failed")


def _same(stored: str, wanted: uuid.UUID) -> bool:
    try:
        return uuid.UUID(stored) == wanted
    except ValueError:
        return False


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


__all__ = ["BotServiceOwnership", "ServiceDisabled"]
