"""Last-resort handlers. Registered after every other router.

Two jobs: translate reply-keyboard taps into the inline flows, and make sure
an unrecognised message gets a helpful Persian nudge instead of silence. A bot
that ignores you feels broken even when it is working perfectly.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from geekvpn.application.bot.read_models import PendingPayment
from geekvpn.application.bot.services import BotServices
from geekvpn.application.payments.receipt_intent import receipt_intent_key
from geekvpn.application.ports.cache import Cache
from geekvpn.presentation.bot.handlers import (
    dashboard,
    faq,
    profile,
    referral,
    server_status,
    settings,
    shop,
    support,
    wallet,
)
from geekvpn.presentation.bot.handlers.common import answer, toast
from geekvpn.presentation.bot.handlers.menu import render_home
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import text as T

router = Router(name="fallback")


@router.message(F.text == T.MENU_SHOP)
async def tap_shop(message: Message, state: FSMContext, **kwargs: Any) -> None:
    await state.clear()
    await shop.open_storefront(
        message,
        user=kwargs.get("user"),
        scope=kwargs.get("scope"),
        services=kwargs.get("services"),
    )


@router.message(F.text == T.MENU_DASHBOARD)
async def tap_dashboard(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await dashboard.on_services_command(message, state, services, user)


@router.message(F.text == T.MENU_WALLET)
async def tap_wallet(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await wallet.on_wallet_command(message, state, services, user)


@router.message(F.text == T.MENU_REFERRAL)
async def tap_referral(
    message: Message,
    state: FSMContext,
    services: BotServices,
    bot: Any = None,
    user: Any = None,
) -> None:
    await referral.on_referral_command(message, state, services, bot, user)


@router.message(F.text == T.MENU_SUPPORT)
async def tap_support(message: Message, state: FSMContext) -> None:
    await support.on_support_command(message, state)


@router.message(F.text == T.MENU_PROFILE)
async def tap_profile(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await profile.on_profile_command(message, state, services, user)


@router.message(F.text == T.MENU_FAQ)
async def tap_faq(message: Message, state: FSMContext) -> None:
    await faq.on_faq_command(message, state)


@router.message(F.text == T.MENU_SETTINGS)
async def tap_settings(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await settings.on_settings_command(message, state, services, user)


@router.message(F.text == T.MENU_STATUS)
async def tap_status(message: Message, state: FSMContext, services: BotServices) -> None:
    await server_status.on_status_command(message, state, services)


def _intended(pending: list[PendingPayment], intent: str | None) -> PendingPayment | None:
    """The payment the customer said this receipt is for, if it is still open.

    The intent is a hint from the Mini App, not an authority: it is matched
    against what this customer actually has awaiting proof, so a stale one -
    or someone else's - selects nothing and falls through to the guess.
    """
    if intent is None:
        return None
    return next((payment for payment in pending if payment.payment_id.hex == intent), None)


@router.message(F.photo)
async def stray_receipt(
    message: Message,
    state: FSMContext,
    services: BotServices,
    cache: Cache,
    user: Any = None,
) -> None:
    """A receipt photo with no flow behind it.

    Every other photo handler is scoped to an FSM state and has already had its
    turn by the time a message reaches this router. What lands here is a photo
    sent by someone the bot is not mid-conversation with - which is exactly
    what a Mini App card payment produces. That flow closes the app and leaves
    the customer in the chat with no state at all, so the photo they were told
    to send matched nothing and got the generic "I did not understand that".
    They had transferred the money and had no way to prove it, and the payment
    sat in AWAITING_PROOF where no reviewer looks.

    Attaching it to the single payment that is waiting for one is the whole
    fix. Two waiting payments is not a guess worth making: attaching the wrong
    receipt produces an approval against the wrong order.
    """
    if user is None or not message.photo:
        # Never silent. A handler that matches and answers nothing is
        # indistinguishable from a bot that is down, and this one fires on a
        # customer holding proof of a transfer they have already made.
        await answer(message, T.ERR_SESSION_EXPIRED, reply_markup=K.main_menu())
        return

    pending = await services.checkout.awaiting_proof(user.id)
    if not pending:
        await answer(message, T.PAY_RECEIPT_NO_PENDING, reply_markup=K.main_menu())
        return

    key = receipt_intent_key(user.telegram_id)
    chosen = _intended(pending, await cache.get(key))
    if chosen is None:
        if len(pending) > 1:
            await answer(message, T.PAY_RECEIPT_AMBIGUOUS, reply_markup=K.main_menu())
            return
        chosen = pending[0]

    payment = await services.checkout.attach_receipt(
        user.id,
        payment_id=chosen.payment_id,
        file_id=message.photo[-1].file_id,
    )
    # Spent, so the next photo is judged on its own. Left behind, it would
    # attach a second receipt to a payment that already has one.
    await cache.delete(key)
    await state.clear()
    await answer(
        message,
        T.PAY_RECEIPT_RECEIVED.format(ref=f"<code>{payment.reference}</code>"),
        reply_markup=K.main_menu(),
    )


@router.message()
async def unknown_message(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    """Anything we did not understand.

    Clears state first: reaching here usually means the user abandoned a flow
    mid-way, and leaving them in a dangling FSM state would swallow their
    next message too.
    """
    await state.clear()
    await answer(message, T.ERR_UNKNOWN_COMMAND, reply_markup=K.main_menu())
    if user is not None:
        body, markup = await render_home(user=user, services=services)
        await answer(message, body, reply_markup=markup)


@router.callback_query()
async def unknown_callback(query: CallbackQuery) -> None:
    """A button from a deploy whose callback schema no longer exists."""
    await toast(query, T.ERR_STALE_BUTTON, alert=True)
