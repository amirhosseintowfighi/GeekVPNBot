"""Outbound notifications.

This is the push side of the bot: expiry warnings, quota warnings, payment
outcomes, and broadcasts. It is called by schedulers and by the admin panel,
not by handlers.

Three rules are enforced here rather than at every call site:

1. **Preferences are honoured.** A user who muted promotions never receives
   one, even if a campaign job asks us to send it.
2. **Quiet hours are honoured** for non-critical categories. A traffic warning
   at 3am is worse than useless. Critical notices (payment approved, service
   expired) always go through -- they are transactional, not marketing.
3. **A blocked user does not raise.** People block bots constantly; that is a
   normal outcome to record, not an exception to propagate into a scheduler.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

from geekvpn.application.bot.read_models import NotificationPreferences
from geekvpn.presentation.bot.handlers.common import local_hour
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB
from geekvpn.presentation.bot.ui.fa import fa_digits, gib, toman

QUIET_START = 23
QUIET_END = 8


class Category(str, Enum):
    """Which preference switch governs a notification, and how urgent it is."""

    EXPIRY = "expiry"
    TRAFFIC = "traffic"
    PROMOS = "promos"
    NEWS = "news"
    CRITICAL = "critical"

    @property
    def bypasses_quiet_hours(self) -> bool:
        return self is Category.CRITICAL

    @property
    def preference_key(self) -> str | None:
        return None if self is Category.CRITICAL else self.value


@dataclass(frozen=True, slots=True)
class Delivery:
    user_id: Any
    delivered: bool
    reason: str = ""


class PreferencesSource(Protocol):
    async def load(self, user_id: Any) -> NotificationPreferences: ...


class ChatIdResolver(Protocol):
    async def telegram_id(self, user_id: Any) -> int | None: ...


def in_quiet_hours(now: datetime) -> bool:
    """Quiet window wraps midnight, so this is an OR, not an AND."""
    hour = local_hour(now)
    return hour >= QUIET_START or hour < QUIET_END


class Notifier:
    def __init__(
        self,
        *,
        bot: Any,
        preferences: PreferencesSource,
        chat_ids: ChatIdResolver,
    ) -> None:
        self._bot = bot
        self._preferences = preferences
        self._chat_ids = chat_ids

    async def send(
        self,
        *,
        user_id: Any,
        category: Category,
        body: str,
        markup: Any = None,
        now: datetime | None = None,
    ) -> Delivery:
        key = category.preference_key
        preferences = None

        if key is not None:
            try:
                preferences = await self._preferences.load(user_id)
            except Exception:
                preferences = NotificationPreferences()
            if not preferences.as_dict().get(key, True):
                return Delivery(user_id, False, "muted")

        if not category.bypasses_quiet_hours:
            quiet_enabled = preferences.quiet_hours if preferences else True
            # UTC, not local: every other timestamp in the system is UTC, and
            # a naive local `now()` makes quiet hours depend on the timezone of
            # whichever container happened to run the job.
            if quiet_enabled and in_quiet_hours(now or datetime.now(UTC)):
                return Delivery(user_id, False, "quiet_hours")

        chat_id = await self._chat_ids.telegram_id(user_id)
        if chat_id is None:
            return Delivery(user_id, False, "no_chat_id")

        try:
            await self._bot.send_message(chat_id, body, reply_markup=markup)
        except Exception as exc:
            return Delivery(user_id, False, type(exc).__name__)

        return Delivery(user_id, True)

    # ---- Typed notifications -------------------------------------------
    # Each one owns its Persian copy and its call-to-action, so a scheduler
    # only supplies facts and never builds user-facing strings.

    async def expiring_soon(
        self, *, user_id: Any, plan_name: str, days_left: int, now: datetime | None = None
    ) -> Delivery:
        body = T.NOTIFY_EXPIRING.format(plan=plan_name, days=fa_digits(days_left))
        return await self.send(
            user_id=user_id,
            category=Category.EXPIRY,
            body=body,
            markup=K.single(K.btn(T.BTN_RENEW, NavCB(to="dashboard"))),
            now=now,
        )

    async def expired(
        self, *, user_id: Any, plan_name: str, now: datetime | None = None
    ) -> Delivery:
        return await self.send(
            user_id=user_id,
            category=Category.CRITICAL,
            body=T.NOTIFY_EXPIRED.format(plan=plan_name),
            markup=K.single(K.btn(T.BTN_RENEW, NavCB(to="shop"))),
            now=now,
        )

    async def quota_warning(
        self,
        *,
        user_id: Any,
        plan_name: str,
        used_gib: float,
        total_gib: float,
        percent: int,
        now: datetime | None = None,
    ) -> Delivery:
        body = T.NOTIFY_QUOTA.format(
            plan=plan_name,
            percent=fa_digits(percent),
            used=gib(used_gib),
            total=gib(total_gib),
        )
        return await self.send(
            user_id=user_id,
            category=Category.TRAFFIC,
            body=body,
            markup=K.single(K.btn(T.BTN_SHOP_NOW, NavCB(to="shop"))),
            now=now,
        )

    async def payment_approved(
        self, *, user_id: Any, amount: int, reference: str, now: datetime | None = None
    ) -> Delivery:
        return await self.send(
            user_id=user_id,
            category=Category.CRITICAL,
            body=T.NOTIFY_PAYMENT_APPROVED.format(
                amount=toman(amount), ref=f"<code>{reference}</code>"
            ),
            markup=K.single(K.btn(T.MENU_DASHBOARD, NavCB(to="dashboard"))),
            now=now,
        )

    async def payment_rejected(
        self, *, user_id: Any, reference: str, reason_fa: str, now: datetime | None = None
    ) -> Delivery:
        return await self.send(
            user_id=user_id,
            category=Category.CRITICAL,
            body=T.NOTIFY_PAYMENT_REJECTED.format(
                ref=f"<code>{reference}</code>", reason=reason_fa
            ),
            markup=K.single(K.btn(T.MENU_SUPPORT, NavCB(to="support"))),
            now=now,
        )

    async def wallet_credited(
        self, *, user_id: Any, amount: int, balance: int, now: datetime | None = None
    ) -> Delivery:
        return await self.send(
            user_id=user_id,
            category=Category.CRITICAL,
            body=T.NOTIFY_WALLET_CREDITED.format(amount=toman(amount), balance=toman(balance)),
            markup=K.single(K.btn(T.MENU_WALLET, NavCB(to="wallet"))),
            now=now,
        )

    async def referral_reward(
        self, *, user_id: Any, amount: int, now: datetime | None = None
    ) -> Delivery:
        return await self.send(
            user_id=user_id,
            category=Category.PROMOS,
            body=T.NOTIFY_REFERRAL_REWARD.format(amount=toman(amount)),
            markup=K.single(K.btn(T.MENU_REFERRAL, NavCB(to="referral"))),
            now=now,
        )

    async def ticket_reply(
        self, *, user_id: Any, reference: str, now: datetime | None = None
    ) -> Delivery:
        return await self.send(
            user_id=user_id,
            category=Category.CRITICAL,
            body=T.NOTIFY_TICKET_REPLY.format(ref=f"<code>{reference}</code>"),
            markup=K.single(K.btn(T.BTN_MY_TICKETS, NavCB(to="support"))),
            now=now,
        )

    async def promo(self, *, user_id: Any, body: str, now: datetime | None = None) -> Delivery:
        return await self.send(
            user_id=user_id,
            category=Category.PROMOS,
            body=body,
            markup=K.single(K.btn(T.BTN_SHOP_NOW, NavCB(to="shop"))),
            now=now,
        )

    async def broadcast(
        self, *, user_ids: list[Any], body: str, category: Category = Category.NEWS
    ) -> list[Delivery]:
        """Sequential on purpose.

        Telegram's global send ceiling is ~30/second; firing a thousand
        concurrent sends earns a 429 and a retry-after, which is slower than
        just pacing ourselves.
        """
        return [
            await self.send(user_id=user_id, category=category, body=body) for user_id in user_ids
        ]
