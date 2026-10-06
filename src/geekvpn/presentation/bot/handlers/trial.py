"""The free trial, from inside the bot.

Until now it lived only in the Android app and the Mini App, so a customer who
never left Telegram could not try the service before paying for it.

Two steps rather than one tap: the first screen says what the trial is and
that it can be had once. A one-tap claim spent the customer's only trial on an
exploratory press.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from geekvpn.application.bot.services import BotServices
from geekvpn.domain.provisioning.errors import FreeTrialAlreadyClaimed, FreeTrialUnavailable
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.bot.handlers.common import safe_edit, short_ref, toast
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import render as R
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB, SubCB, TrialCB
from geekvpn.presentation.bot.ui.fa import fa_digits, gib

logger = get_logger("bot.trial")

router = Router(name="trial")

MIB_PER_GIB = 1024


def _size(traffic_mib: int) -> str:
    if traffic_mib >= MIB_PER_GIB:
        return gib(traffic_mib / MIB_PER_GIB)
    return f"{fa_digits(traffic_mib)} مگابایت"


def _back() -> InlineKeyboardMarkup:
    return K.single(K.home_button())


@router.callback_query(TrialCB.filter(F.action == "view"))
async def on_view(query: CallbackQuery, services: BotServices, user: Any = None) -> None:
    await toast(query)
    if user is None or services.trial is None:
        return
    offer = await services.trial.offer(user.id)
    if not offer.available:
        await safe_edit(query, T.TRIAL_UNAVAILABLE, markup=_back())
        return
    body = offer.intro_fa or T.TRIAL_INTRO.format(
        traffic=_size(offer.traffic_mib), days=fa_digits(offer.duration_days)
    )
    await safe_edit(
        query,
        body,
        markup=K.stack(
            [
                [K.btn(T.BTN_TRIAL_CLAIM, TrialCB(action="claim"), style=K.YES)],
                [K.home_button()],
            ]
        ),
    )


@router.callback_query(TrialCB.filter(F.action == "claim"))
async def on_claim(query: CallbackQuery, services: BotServices, user: Any = None) -> None:
    await toast(query)
    if user is None or services.trial is None:
        return
    await safe_edit(query, T.TRIAL_WORKING)
    try:
        result = await services.trial.claim(user.id)
    except FreeTrialAlreadyClaimed:
        await safe_edit(query, T.TRIAL_ALREADY_CLAIMED, markup=_shop_markup())
        return
    except FreeTrialUnavailable:
        await safe_edit(query, T.TRIAL_UNAVAILABLE, markup=_back())
        return

    if not result.cards:
        await safe_edit(query, T.TRIAL_ONLY_PENDING, markup=_dashboard_markup())
    else:
        body = T.TRIAL_DELIVERED
        if result.pending:
            body += T.TRIAL_PENDING_LINE.format(count=fa_digits(result.pending))
        rows = [
            [
                K.btn(
                    R.subscription_button_label(card),
                    SubCB(action="view", ref=short_ref(card.subscription_id)),
                    style=K.GO,
                )
            ]
            for card in result.cards
        ]
        rows.append([K.home_button()])
        await safe_edit(query, body, markup=K.stack(rows))

    if result.after_message_fa and query.message is not None:
        # A message of its own, not appended: the operator's text is often a
        # tutorial link or a channel invite the customer should be able to find
        # again after the screen above has been edited away.
        await query.message.answer(result.after_message_fa)


def _shop_markup() -> InlineKeyboardMarkup:
    return K.stack([[K.btn(T.BTN_SHOP_NOW, NavCB(to="shop"), style=K.YES)], [K.home_button()]])


def _dashboard_markup() -> InlineKeyboardMarkup:
    return K.stack(
        [[K.btn(T.MENU_DASHBOARD, NavCB(to="dashboard"), style=K.GO)], [K.home_button()]]
    )
