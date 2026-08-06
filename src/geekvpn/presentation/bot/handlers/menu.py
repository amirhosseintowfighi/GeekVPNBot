"""Home screen and top-level navigation.

`render_home` is imported by several other handlers so that "go home" always
produces a *freshly loaded* home screen rather than a cached body. A stale
wallet balance on the main menu is exactly the kind of thing that generates a
support ticket.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from geekvpn.application.bot.read_models import SubscriptionState
from geekvpn.presentation.bot.handlers.common import (
    display_name_of,
    local_hour,
    safe_edit,
    tier_emoji,
    tier_label,
    tier_of,
    toast,
)
from geekvpn.presentation.bot.services import BotServices
from geekvpn.presentation.bot.ui import emoji as E
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import render as R
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB, NoopCB

router = Router(name="menu")

_LIVE_STATES = (SubscriptionState.ACTIVE, SubscriptionState.EXPIRING)


def home_keyboard() -> InlineKeyboardMarkup:
    return K.stack(
        [
            [
                K.btn(f"{E.SHOP} {T.MENU_SHOP}", NavCB(to="shop")),
                K.btn(f"{E.DASHBOARD} {T.MENU_DASHBOARD}", NavCB(to="dashboard")),
            ],
            [
                K.btn(f"{E.WALLET} {T.MENU_WALLET}", NavCB(to="wallet")),
                K.btn(f"{E.REFERRAL} {T.MENU_REFERRAL}", NavCB(to="referral")),
            ],
        ]
    )


async def render_home(
    *,
    user: Any,
    services: BotServices,
    name: str | None = None,
    now: datetime | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Load and compose the home screen.

    Tolerant by design: if the wallet or subscription reader fails we still
    render a usable menu with zeros rather than an error, because the main
    menu is the one screen that must never be broken.
    """
    moment = now or datetime.now(UTC)

    try:
        snapshot = await services.wallet.snapshot(user.id)
    except Exception:
        from geekvpn.application.bot.read_models import WalletSnapshot

        snapshot = WalletSnapshot()

    try:
        cards = await services.subscriptions.list_for_user(user.id)
    except Exception:
        cards = []

    active = sum(1 for c in cards if c.state in _LIVE_STATES)
    tier = tier_of(snapshot.lifetime_spend)

    body = R.home(
        name=name or display_name_of(user),
        hour=local_hour(moment),
        balance=snapshot.balance,
        tier_label=tier_label(tier),
        tier_emoji=tier_emoji(tier),
        active_count=active,
    )
    return body, home_keyboard()


@router.callback_query(NavCB.filter(F.to == "home"))
async def on_home(
    query: CallbackQuery,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
) -> None:
    await state.clear()
    await toast(query)
    if user is None:
        return
    body, markup = await render_home(user=user, services=services)
    await safe_edit(query, body, markup=markup)


@router.message(F.text.contains(T.MENU_SHOP))
async def on_shop_text(message: Message, state: FSMContext, **_: Any) -> None:
    """Reply-keyboard entry points delegate to the inline flows.

    Implemented as a thin forward rather than duplicated logic so the reply
    keyboard and the inline keyboard can never drift apart.
    """
    from geekvpn.presentation.bot.handlers import shop

    await state.clear()
    await shop.open_storefront(message, **_)


@router.callback_query(NoopCB.filter())
async def on_noop(query: CallbackQuery) -> None:
    """Label-only buttons: stop the spinner, change nothing."""
    await toast(query)
