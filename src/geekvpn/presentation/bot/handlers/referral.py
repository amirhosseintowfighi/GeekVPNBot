"""Referral programme.

The share button uses a `t.me/share/url` deep link rather than copying text
to the clipboard, because Telegram has no clipboard API and asking a user to
long-press-copy a link is where referral funnels die.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from geekvpn.application.bot.read_models import ReferralSummary
from geekvpn.presentation.bot.handlers.common import answer, safe_edit, toast
from geekvpn.presentation.bot.services import BotServices
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import render as R
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB, RefCB

router = Router(name="referral")

# Mirrors the pricing policy defaults. Displayed only -- the authoritative
# numbers are applied server-side at accrual time.
DEFAULT_INVITEE_BONUS = 50_000
DEFAULT_FIRST_BPS = 1_000
DEFAULT_RECURRING_BPS = 300


def referral_link(*, bot_username: str, code: str) -> str:
    return f"https://t.me/{bot_username}?start=ref_{code}"


def _keyboard(link: str) -> InlineKeyboardMarkup:
    share_url = (
        "https://t.me/share/url?url="
        + quote(link, safe="")
        + "&text="
        + quote(T.REF_SHARE_TEXT, safe="")
    )
    return K.stack(
        [
            [K.url_btn(T.BTN_SHARE_LINK, share_url)],
            [K.btn(T.BTN_REF_STATS, RefCB(action="stats", ref="-"))],
            [K.home_button()],
        ]
    )


async def _load(services: BotServices, user: Any) -> ReferralSummary:
    try:
        return await services.referrals.summary(user.id)
    except Exception:
        return ReferralSummary(code="")


async def _render(services: BotServices, user: Any, *, bot_username: str) -> tuple[str, Any]:
    summary = await _load(services, user)
    link = referral_link(bot_username=bot_username, code=summary.code)
    body = R.referral(
        summary,
        link=link,
        invitee_bonus=DEFAULT_INVITEE_BONUS,
        first_rate_bps=DEFAULT_FIRST_BPS,
        recurring_rate_bps=DEFAULT_RECURRING_BPS,
    )
    return body, _keyboard(link)


async def _bot_username(bot: Any) -> str:
    try:
        me = await bot.me()
        return me.username or ""
    except Exception:
        return ""


@router.message(Command("referral"))
async def on_referral_command(
    message: Message,
    state: FSMContext,
    services: BotServices,
    bot: Any = None,
    user: Any = None,
) -> None:
    await state.clear()
    if user is None:
        await answer(message, T.ERR_GENERIC)
        return
    body, markup = await _render(services, user, bot_username=await _bot_username(bot))
    await answer(message, body, reply_markup=markup)


@router.callback_query(NavCB.filter(F.to == "referral"))
async def on_referral(
    query: CallbackQuery,
    state: FSMContext,
    services: BotServices,
    bot: Any = None,
    user: Any = None,
) -> None:
    await state.clear()
    await toast(query)
    if user is None:
        return
    body, markup = await _render(services, user, bot_username=await _bot_username(bot))
    await safe_edit(query, body, markup=markup)


@router.callback_query(RefCB.filter(F.action == "stats"))
async def on_stats(query: CallbackQuery, services: BotServices, user: Any = None) -> None:
    await toast(query)
    if user is None:
        return
    summary = await _load(services, user)
    if summary.converted_count == 0 and summary.invited_count == 0:
        body = T.REF_STATS_EMPTY
    else:
        from geekvpn.presentation.bot.ui.fa import fa_digits, toman

        body = "\n".join(
            [
                f"<b>{T.REF_STATS_TITLE}</b>",
                "",
                f"\U0001f465 \u062f\u0639\u0648\u062a\u200c\u0634\u062f\u0647\u200c\u0647\u0627: {fa_digits(summary.invited_count)}",
                f"\u2705 \u062e\u0631\u06cc\u062f \u06a9\u0631\u062f\u0647\u200c\u0627\u0646\u062f: {fa_digits(summary.converted_count)}",
                f"\U0001f4b5 \u062f\u0631\u0622\u0645\u062f \u06a9\u0644: {toman(summary.total_earned)}",
                f"\u23f3 \u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631: {toman(summary.pending_earned)}",
            ]
        )
    await safe_edit(query, body, markup=K.single(K.btn(T.BTN_BACK, NavCB(to="referral"))))
