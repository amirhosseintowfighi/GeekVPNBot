"""The bundle of read-model ports handed to every handler.

Built once per update by `IdentityMiddleware` and injected as workflow data,
so aiogram hands it by name to any handler declaring a `services: BotServices`
parameter. This keeps handlers free of container lookups and makes them
trivially testable -- a test builds a `BotServices` of fakes and calls the
handler directly.

It lives in the application layer because it names only application ports.
Keeping it in `presentation` forced infrastructure to import presentation in
order to assemble it, which the layering contract rightly refuses.
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
