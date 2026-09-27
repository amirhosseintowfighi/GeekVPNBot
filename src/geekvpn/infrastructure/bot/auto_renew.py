"""The worker's half of auto-renewal: charging a wallet the way the bot does.

A renewal from the wallet is exactly what the bot's "renew" button does when
the customer picks the wallet - quote, order, debit, provision onto the same
service - so it goes through the same `BotCheckoutAdapter.pay_from_wallet`
rather than a second path that could price or provision differently.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from geekvpn.application.platform.settings_service import AUTO_RENEW_ENABLED
from geekvpn.application.provisioning.auto_renewal import (
    AutoRenewal,
    ChargeResult,
    RenewalOutcome,
)
from geekvpn.domain.analytics.calendar import to_jalali
from geekvpn.domain.base.errors import DomainError
from geekvpn.domain.notifications.message import RenderedMessage
from geekvpn.domain.payments.errors import InsufficientFunds
from geekvpn.domain.provisioning.errors import DeliveryPending
from geekvpn.domain.provisioning.subscription import Subscription
from geekvpn.infrastructure.bot.checkout import BotCheckoutAdapter
from geekvpn.infrastructure.bot.sync_readers import SyncBridge
from geekvpn.infrastructure.cache.redis import RedisCache
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.di.scope import build_scope
from geekvpn.infrastructure.di.sync_scope import SyncScope
from geekvpn.infrastructure.logging.setup import get_logger

logger = get_logger("worker.auto_renew")

#: Longer than any service could stay inside the renewal window, so an attempt
#: is remembered until its expiry has passed.
ATTEMPT_TTL = timedelta(days=7)


class CacheAttemptLog:
    """``AttemptLog`` over the shared cache, so a restart does not retry."""

    def __init__(self, cache: RedisCache) -> None:
        self._cache = cache

    async def seen(self, key: str) -> bool:
        return await self._cache.get(f"auto_renew:{key}") is not None

    async def mark(self, key: str) -> None:
        await self._cache.set(
            f"auto_renew:{key}", "1", ttl_seconds=int(ATTEMPT_TTL.total_seconds())
        )


async def charge_from_wallet(container: Container, subscription: Subscription) -> ChargeResult:
    """Renew one service onto its own plan, from its owner's wallet.

    Its own session: each renewal commits on its own, so one customer's panel
    failing cannot roll back another customer's renewal.
    """
    if subscription.plan_id is None:
        return ChargeResult(RenewalOutcome.NOT_RENEWABLE)
    reseller_id = _reseller(subscription)

    async with container.session_factory() as session:
        scope = build_scope(container, session)
        try:
            user = await scope.users.get_by_telegram_id(
                subscription.user_id, reseller_id=reseller_id
            )
            plan_id = uuid.UUID(subscription.plan_id)
            plan = await scope.catalog_plans.get(plan_id)
            if user is None or plan is None or not plan.is_visible:
                return ChargeResult(RenewalOutcome.NOT_RENEWABLE)
            jalali_year, _, _ = to_jalali(container.clock.now().date())
            checkout = BotCheckoutAdapter(
                bridge=SyncBridge(container=container, users=scope.users, reseller_id=reseller_id),
                quoting=scope.quoting,
                orders=scope.order_service,
                order_repository=scope.orders,
                provisioning=scope.provisioning,
                session=session,
                plans=scope.catalog_plans,
                coupons=scope.catalog_coupons,
                subscriptions=scope.subscriptions,
                clock=container.clock,
                jalali_year=jalali_year,
            )
            quote = await scope.quoting.quote(plan_id=plan_id, user_id=user.id)
            try:
                await checkout.pay_from_wallet(
                    user.id, plan_id=plan_id, renews_subscription_id=subscription.id
                )
            except InsufficientFunds as short:
                return ChargeResult(
                    RenewalOutcome.SHORT, amount=int(short.details.get("shortfall", 0))
                )
            except DeliveryPending:
                # Paid, and the retry queue owes the service: renewed as far as
                # the customer's money is concerned.
                pass
            await session.commit()
            return ChargeResult(RenewalOutcome.RENEWED, amount=quote.total.amount)
        except DomainError:
            await session.rollback()
            logger.warning("auto_renew.refused", subscription=subscription.id, exc_info=True)
            return ChargeResult(RenewalOutcome.FAILED)
        finally:
            await scope.aclose()


class _Candidates:
    def __init__(self, container: Container) -> None:
        self._container = container

    async def list_auto_renew_due(
        self, *, before: datetime, limit: int = 200
    ) -> Sequence[Subscription]:
        async with self._container.session_factory() as session:
            scope = build_scope(self._container, session)
            try:
                return await scope.subscriptions.list_auto_renew_due(before=before, limit=limit)
            finally:
                await scope.aclose()


def build_auto_renewal(container: Container) -> AutoRenewal:
    async def charge(subscription: Subscription) -> ChargeResult:
        return await charge_from_wallet(container, subscription)

    async def notify(subscription: Subscription, message: RenderedMessage) -> None:
        # Through the shop that sold it, so a reseller's customer hears from
        # the reseller's bot rather than ours.
        def work(scope: SyncScope) -> None:
            scope.engine.dispatch(
                user_id=subscription.user_id, message=message, source="renewal.auto"
            )

        async with container.session_factory() as session:
            scope = build_scope(container, session)
            try:
                bridge = SyncBridge(
                    container=container, users=scope.users, reseller_id=_reseller(subscription)
                )
                await bridge.run(work)
            finally:
                await scope.aclose()

    async def enabled() -> bool:
        async with container.session_factory() as session:
            scope = build_scope(container, session)
            try:
                return await scope.settings_service.get(AUTO_RENEW_ENABLED)
            finally:
                await scope.aclose()

    return AutoRenewal(
        candidates=_Candidates(container),
        charge=charge,
        attempts=CacheAttemptLog(container.cache),
        notify=notify,
        enabled=enabled,
        clock=container.clock,
    )


def _reseller(subscription: Subscription) -> uuid.UUID | None:
    return uuid.UUID(subscription.reseller_id) if subscription.reseller_id else None


__all__ = ["CacheAttemptLog", "build_auto_renewal", "charge_from_wallet"]
