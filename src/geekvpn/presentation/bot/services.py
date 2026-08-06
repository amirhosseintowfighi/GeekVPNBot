"""The bundle of read-model ports handed to every handler.

Registered once as dispatcher workflow data, so aiogram injects it by name
into any handler that declares a `services: BotServices` parameter. This keeps
handlers free of container lookups and makes them trivially testable -- a test
builds a `BotServices` of fakes and calls the handler directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from geekvpn.application.bot.ports import (
    CheckoutService,
    PreferencesStore,
    ProfileReader,
    ReferralReader,
    ServerStatusReader,
    SubscriptionReader,
    TicketReader,
    WalletReader,
)


@dataclass(frozen=True, slots=True)
class BotServices:
    subscriptions: SubscriptionReader
    wallet: WalletReader
    referrals: ReferralReader
    profiles: ProfileReader
    servers: ServerStatusReader
    tickets: TicketReader
    preferences: PreferencesStore
    checkout: CheckoutService
