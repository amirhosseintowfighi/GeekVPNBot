"""Assembling ``BotServices``.

The missing piece. Eight ports had no implementations, and even once they had
one there was nowhere that built them into the bundle every handler declares.

The assembly deliberately lives here rather than in ``create_dispatcher``.
``BotServices`` needs a database session, and a dispatcher is constructed once
per process, so a bundle built there would either hold a session for the
lifetime of the bot or hold none at all. ``IdentityMiddleware`` already opens a
unit of work per update, which is the only correct place to build it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from geekvpn.application.bot.services import BotServices
from geekvpn.domain.analytics.calendar import to_jalali
from geekvpn.infrastructure.bot.checkout import BotCheckoutAdapter
from geekvpn.infrastructure.bot.readers import (
    SqlProfileReader,
    SqlReferralSummaryReader,
    SqlServerStatusReader,
    SqlSubscriptionCardReader,
)
from geekvpn.infrastructure.bot.sync_readers import (
    SyncBridge,
    SyncPreferencesCardStore,
    SyncTicketCardReader,
    SyncWalletCardReader,
)
from geekvpn.infrastructure.di.scope import RequestScope


def build_bot_services(
    scope: RequestScope,
    *,
    fetch_receipt: Callable[[str], Awaitable[bytes]] | None = None,
) -> BotServices:
    """Build the bundle for one update.

    :param fetch_receipt: downloads a Telegram file so a receipt can be
        fingerprinted from its bytes. Without it ``attach_receipt`` refuses:
        see the note in ``bot/checkout.py`` about why hashing the file id is
        not an acceptable fallback.
    """
    container = scope.container
    bridge = SyncBridge(container=container, users=scope.users)
    jalali_year, _, _ = to_jalali(container.clock.now().date())

    return BotServices(
        subscriptions=SqlSubscriptionCardReader(
            users=scope.users,
            subscriptions=scope.subscriptions,
            orders=scope.orders,
        ),
        wallet=SyncWalletCardReader(bridge),
        referrals=SqlReferralSummaryReader(session=scope.session, users=scope.users),
        profiles=SqlProfileReader(users=scope.users, orders=scope.orders),
        servers=SqlServerStatusReader(nodes=scope.nodes),
        tickets=SyncTicketCardReader(bridge),
        preferences=SyncPreferencesCardStore(bridge),
        checkout=BotCheckoutAdapter(
            bridge=bridge,
            quoting=scope.quoting,
            orders=scope.order_service,
            order_repository=scope.orders,
            provisioning=scope.provisioning,
            session=scope.session,
            plans=scope.catalog_plans,
            coupons=scope.catalog_coupons,
            clock=container.clock,
            jalali_year=jalali_year,
            fetch_receipt=fetch_receipt,
        ),
    )


__all__ = ["build_bot_services"]
