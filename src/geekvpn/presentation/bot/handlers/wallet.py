"""Wallet: balance, top-up (card-to-card / crypto), transaction history.

Top-up shares the same manual-approval rails as checkout. There is no
auto-credit: money only lands in a wallet after an admin approves the
receipt, because a self-service credit button on an unverified transfer is a
free money glitch.

Amount entry accepts Persian digits and thousands separators, because a
customer typing ۲۰۰٬۰۰۰ should not be told their input is invalid.
"""

from __future__ import annotations

import uuid
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from geekvpn.application.bot.read_models import (
    CardPaymentDetails,
    WalletSnapshot,
)
from geekvpn.application.bot.services import BotServices
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.bot.handlers.common import (
    answer,
    customer_message,
    safe_edit,
    tier_emoji,
    tier_label,
    tier_of,
    toast,
)
from geekvpn.presentation.bot.handlers.purchase import _card_body, _crypto_body
from geekvpn.presentation.bot.states import Wallet
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import render as R
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB, PageCB, WalletCB
from geekvpn.presentation.bot.ui.fa import normalize_input, toman

logger = get_logger("bot.wallet")

router = Router(name="wallet")

MIN_TOPUP = 50_000
MAX_TOPUP = 50_000_000
PRESETS = (200_000, 500_000, 1_000_000, 2_000_000)
PAGE_SIZE = 8


def _wallet_keyboard() -> InlineKeyboardMarkup:
    return K.stack(
        [
            [K.btn(T.BTN_TOPUP, WalletCB(action="topup", ref="-"), style=K.YES)],
            [K.btn(T.BTN_WALLET_HISTORY, WalletCB(action="history", ref="-"))],
            [K.home_button()],
        ]
    )


def _preset_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [K.btn(toman(amount), WalletCB(action="amount", ref=str(amount)))] for amount in PRESETS
    ]
    rows.append([K.btn(T.BTN_CANCEL, NavCB(to="wallet"))])
    return K.stack(rows)


def _method_keyboard() -> InlineKeyboardMarkup:
    return K.stack(
        [
            [K.btn(T.PAY_CARD, WalletCB(action="m_card", ref="-"))],
            [K.btn(T.PAY_CRYPTO, WalletCB(action="m_crypto", ref="-"))],
            [K.btn(T.BTN_CANCEL, NavCB(to="wallet"))],
        ]
    )


async def _snapshot(services: BotServices, user: Any) -> WalletSnapshot:
    try:
        return await services.wallet.snapshot(user.id)
    except Exception:
        # An empty wallet is a safe thing to *draw* and a terrible thing to
        # believe: a customer whose balance failed to load sees zero, and a
        # zero balance is indistinguishable from a spent one. Never silently.
        logger.exception("bot.wallet_snapshot_failed", user_id=getattr(user, "id", None))
        return WalletSnapshot()


async def _render_wallet(services: BotServices, user: Any) -> str:
    snapshot = await _snapshot(services, user)
    tier = tier_of(snapshot.lifetime_spend)
    return R.wallet(snapshot, tier_label=tier_label(tier), tier_emoji=tier_emoji(tier))


@router.message(Command("wallet"))
async def on_wallet_command(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await state.clear()
    if user is None:
        await answer(message, T.ERR_GENERIC)
        return
    await answer(message, await _render_wallet(services, user), reply_markup=_wallet_keyboard())


@router.callback_query(NavCB.filter(F.to == "wallet"))
async def on_wallet(
    query: CallbackQuery, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await state.set_state(Wallet.idle)
    await toast(query)
    if user is None:
        return
    await safe_edit(query, await _render_wallet(services, user), markup=_wallet_keyboard())


@router.callback_query(WalletCB.filter(F.action == "topup"))
async def on_topup(query: CallbackQuery, state: FSMContext) -> None:
    await toast(query)
    await state.set_state(Wallet.entering_amount)
    body = T.WALLET_ASK_AMOUNT.format(min_amount=toman(MIN_TOPUP), max_amount=toman(MAX_TOPUP))
    await safe_edit(query, body, markup=_preset_keyboard())


@router.callback_query(WalletCB.filter(F.action == "amount"))
async def on_preset(query: CallbackQuery, callback_data: WalletCB, state: FSMContext) -> None:
    await toast(query)
    await state.update_data(amount=int(callback_data.ref))
    await state.set_state(Wallet.choosing_method)
    body = f"{T.PAY_CHOOSE}\n\n{T.LBL_TOTAL}: <b>{toman(int(callback_data.ref))}</b>"
    await safe_edit(query, body, markup=_method_keyboard())


@router.message(Wallet.entering_amount, F.text)
async def on_amount_text(message: Message, state: FSMContext) -> None:
    """Parse a typed amount.

    `normalize_input` folds Persian/Arabic digits to ASCII; we then strip
    every separator a human might plausibly type.
    """
    raw = normalize_input(message.text or "")
    for junk in (",", "\u066c", " ", "\u200c", ".", "\u062a\u0648\u0645\u0627\u0646"):
        raw = raw.replace(junk, "")

    if not raw.isdigit():
        await answer(message, T.WALLET_AMOUNT_INVALID)
        return

    amount = int(raw)
    if amount < MIN_TOPUP:
        await answer(message, T.WALLET_AMOUNT_TOO_LOW.format(min_amount=toman(MIN_TOPUP)))
        return
    if amount > MAX_TOPUP:
        await answer(message, T.WALLET_AMOUNT_TOO_HIGH.format(max_amount=toman(MAX_TOPUP)))
        return

    await state.update_data(amount=amount)
    await state.set_state(Wallet.choosing_method)
    body = f"{T.PAY_CHOOSE}\n\n{T.LBL_TOTAL}: <b>{toman(amount)}</b>"
    await answer(message, body, reply_markup=_method_keyboard())


async def _begin_topup(
    query: CallbackQuery,
    state: FSMContext,
    services: BotServices,
    user: Any,
    method: str,
) -> None:
    data = await state.get_data()
    amount = int(data.get("amount") or 0)
    if amount <= 0:
        await safe_edit(query, T.ERR_SESSION_EXPIRED, markup=K.single(K.home_button()))
        return

    try:
        details = await services.checkout.begin_topup(user_id=user.id, amount=amount, method=method)
    except Exception as failure:
        logger.exception("bot.topup_failed", amount=amount, method=method)
        await safe_edit(query, customer_message(failure), markup=K.single(K.home_button()))
        return

    payment = details.payment
    if payment is None:
        await safe_edit(query, T.ERR_GENERIC, markup=K.single(K.home_button()))
        return
    await state.update_data(payment_id=str(payment.payment_id))

    # The port returns one of exactly two shapes, so there is no third branch
    # to guard: a new payment method would fail the type check here first.
    if isinstance(details, CardPaymentDetails):
        await state.set_state(Wallet.awaiting_receipt)
        body = _card_body(details, amount=payment.amount)
    else:
        await state.set_state(Wallet.awaiting_crypto_txid)
        body = _crypto_body(details, amount=payment.amount)

    await safe_edit(query, body, markup=K.single(K.btn(T.BTN_CANCEL, NavCB(to="wallet"))))


@router.callback_query(WalletCB.filter(F.action == "m_card"))
async def on_topup_card(
    query: CallbackQuery, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await toast(query)
    if user is not None:
        await _begin_topup(query, state, services, user, "card")


@router.callback_query(WalletCB.filter(F.action == "m_crypto"))
async def on_topup_crypto(
    query: CallbackQuery, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await toast(query)
    if user is not None:
        await _begin_topup(query, state, services, user, "crypto")


@router.message(Wallet.awaiting_receipt, F.photo)
async def on_topup_receipt(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    data = await state.get_data()
    payment_id = data.get("payment_id")
    if not payment_id or not message.photo or user is None:
        await answer(message, T.ERR_SESSION_EXPIRED)
        await state.clear()
        return
    payment = await services.checkout.attach_receipt(
        user.id, payment_id=uuid.UUID(str(payment_id)), file_id=message.photo[-1].file_id
    )
    await state.clear()
    await answer(
        message,
        T.PAY_RECEIPT_RECEIVED.format(ref=f"<code>{payment.reference}</code>"),
        reply_markup=K.main_menu(),
    )


@router.message(Wallet.awaiting_receipt)
async def on_topup_receipt_wrong(message: Message) -> None:
    await answer(message, T.PAY_RECEIPT_NOT_IMAGE)


@router.message(Wallet.awaiting_crypto_txid, F.text)
async def on_topup_txid(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    data = await state.get_data()
    payment_id = data.get("payment_id")
    if not payment_id or user is None:
        await answer(message, T.ERR_SESSION_EXPIRED)
        await state.clear()
        return
    txid = normalize_input(message.text or "")
    if len(txid) < 10 or " " in txid:
        await answer(message, T.PAY_CRYPTO_BAD_TXID)
        return
    payment = await services.checkout.attach_txid(
        user.id, payment_id=uuid.UUID(str(payment_id)), txid=txid
    )
    await state.clear()
    await answer(
        message,
        T.PAY_PENDING_REVIEW.format(ref=f"<code>{payment.reference}</code>"),
        reply_markup=K.main_menu(),
    )


@router.callback_query(WalletCB.filter(F.action == "history"))
async def on_history(query: CallbackQuery, services: BotServices, user: Any = None) -> None:
    await toast(query)
    if user is not None:
        await _render_history(query, services, user, page=0)


@router.callback_query(PageCB.filter(F.scope == "wtx"))
async def on_history_page(
    query: CallbackQuery,
    callback_data: PageCB,
    services: BotServices,
    user: Any = None,
) -> None:
    await toast(query)
    if user is not None:
        await _render_history(query, services, user, page=callback_data.page)


async def _render_history(
    query: CallbackQuery, services: BotServices, user: Any, *, page: int
) -> None:
    try:
        transactions = await services.wallet.transactions(
            user.id, limit=PAGE_SIZE, offset=page * PAGE_SIZE
        )
        total = await services.wallet.transaction_count(user.id)
    except Exception:
        # Same reasoning as the snapshot: an empty ledger reads as "you have
        # never transacted", which is a lie a customer will act on.
        logger.exception("bot.wallet_ledger_failed", user_id=getattr(user, "id", None))
        transactions, total = [], 0

    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    rows: list[list[Any]] = []
    if pages > 1:
        rows.append(K.pagination_row(scope="wtx", page=page, total_pages=pages))
    rows.append([K.btn(T.BTN_BACK, NavCB(to="wallet")), K.home_button()])
    await safe_edit(query, R.wallet_history(transactions), markup=K.stack(rows))
