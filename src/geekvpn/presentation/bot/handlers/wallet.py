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
    GatewayScreen,
    WalletSnapshot,
)
from geekvpn.application.bot.services import BotServices
from geekvpn.application.platform.settings_service import (
    TOPUP_MAX_TOMAN,
    TOPUP_MIN_TOMAN,
    TRANSFER_ENABLED_WALLET,
    TRANSFER_MIN_TOMAN,
)
from geekvpn.domain.base.errors import DomainError
from geekvpn.domain.payments.wallet import MAX_TOPUP, MIN_TOPUP
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
from geekvpn.presentation.bot.handlers.purchase import (
    _card_body,
    _crypto_body,
    card_keyboard,
)
from geekvpn.presentation.bot.states import Wallet
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import render as R
from geekvpn.presentation.bot.ui import stickers as S
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB, PageCB, WalletCB
from geekvpn.presentation.bot.ui.fa import normalize_input, toman

logger = get_logger("bot.wallet")

router = Router(name="wallet")

PRESETS = (200_000, 500_000, 1_000_000, 2_000_000)
PAGE_SIZE = 8


def _wallet_keyboard(*, transfer: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [K.btn(T.BTN_TOPUP, WalletCB(action="topup", ref="-"), style=K.YES)],
        [K.btn(T.BTN_WALLET_HISTORY, WalletCB(action="history", ref="-"), style=K.GO)],
    ]
    if transfer:
        rows.append([K.btn(T.BTN_WALLET_SEND, WalletCB(action="send", ref="-"), style=K.GO)])
    rows.append([K.home_button()])
    return K.stack(rows)


async def _transfer_on(scope: Any) -> bool:
    service = getattr(scope, "settings_service", None)
    if service is None:
        return False
    try:
        return bool(await service.get(TRANSFER_ENABLED_WALLET))
    except Exception:
        logger.warning("wallet.transfer_setting_unreadable", exc_info=True)
        return False


def _preset_keyboard(low: int = MIN_TOPUP, high: int = MAX_TOPUP) -> InlineKeyboardMarkup:
    """Two per row, and none of them coloured.

    They were a single column of four, each one green. Both were wrong for the
    same reason: the labels are short enough that a column wastes most of the
    width and pushes the cancel button off the first screen, and colouring
    every option green recommends none of them. This screen is a choice
    between four equals - the colour belongs on the confirm that follows.
    """
    presets = [
        K.btn(toman(amount), WalletCB(action="amount", ref=str(amount)))
        for amount in PRESETS
        # A preset outside the shop's range would only be refused a tap later.
        if low <= amount <= high
    ]
    builder = K.grid(presets, width=2)
    builder.inline_keyboard.append([K.btn(T.BTN_CANCEL, NavCB(to="wallet"), style=K.NO)])
    return builder


def _method_keyboard(methods: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Whatever this shop can take money by - asked, not assumed.

    It used to be two hardcoded buttons, card and crypto, so this screen was
    the one place a configured gateway could never appear: the purchase screen
    had been made registry-driven and this one was missed. It also offered
    crypto to shops that had no address registered, which ended in an apology.
    """
    rows: list[list[Any]] = [
        [K.btn(label, WalletCB(action="method", ref=key), style=K.GO)] for key, label in methods
    ]
    rows.append([K.btn(T.BTN_CANCEL, NavCB(to="wallet"), style=K.NO)])
    return K.stack(rows)


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
    message: Message,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
    scope: Any = None,
) -> None:
    await state.clear()
    if user is None:
        await answer(message, T.ERR_GENERIC)
        return
    await answer(
        message,
        await _render_wallet(services, user),
        reply_markup=_wallet_keyboard(transfer=await _transfer_on(scope)),
    )


@router.callback_query(NavCB.filter(F.to == "wallet"))
async def on_wallet(
    query: CallbackQuery,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
    scope: Any = None,
) -> None:
    await state.set_state(Wallet.idle)
    await toast(query)
    if user is None:
        return
    await safe_edit(
        query,
        await _render_wallet(services, user),
        markup=_wallet_keyboard(transfer=await _transfer_on(scope)),
    )


# -- sending balance to another customer -------------------------------------


def _digits(text: str) -> str:
    raw = normalize_input(text)
    for junk in (",", "\u066c", " ", "\u200c", ".", "\u062a\u0648\u0645\u0627\u0646"):
        raw = raw.replace(junk, "")
    return raw


async def _transfer_minimum(scope: Any) -> int:
    try:
        return int(await scope.settings_service.get(TRANSFER_MIN_TOMAN))
    except Exception:
        logger.warning("wallet.transfer_minimum_unreadable", exc_info=True)
        return int(TRANSFER_MIN_TOMAN.default)


@router.callback_query(WalletCB.filter(F.action == "send"))
async def on_send(query: CallbackQuery, state: FSMContext, scope: Any = None) -> None:
    if not await _transfer_on(scope):
        await toast(query, T.WALLET_SEND_OFF, alert=True)
        return
    await toast(query)
    await state.set_state(Wallet.transfer_recipient)
    await safe_edit(
        query, T.WALLET_SEND_ASK_RECIPIENT, markup=K.single(K.btn(T.BTN_CANCEL, NavCB(to="wallet")))
    )


@router.message(Wallet.transfer_recipient, F.text)
async def on_send_recipient(
    message: Message,
    state: FSMContext,
    services: BotServices,
    scope: Any = None,
    user: Any = None,
) -> None:
    raw = _digits(message.text or "")
    if not raw.isdigit() or user is None:
        await answer(message, T.WALLET_SEND_BAD_ID)
        return
    await state.update_data(transfer_to=int(raw))
    await state.set_state(Wallet.transfer_amount)
    snapshot = await _snapshot(services, user)
    await answer(
        message,
        T.WALLET_SEND_ASK_AMOUNT.format(
            min_amount=toman(await _transfer_minimum(scope)), balance=toman(snapshot.balance)
        ),
        reply_markup=K.single(K.btn(T.BTN_CANCEL, NavCB(to="wallet"))),
    )


@router.message(Wallet.transfer_amount, F.text)
async def on_send_amount(message: Message, state: FSMContext) -> None:
    raw = _digits(message.text or "")
    if not raw.isdigit() or int(raw) <= 0:
        await answer(message, T.WALLET_AMOUNT_INVALID)
        return
    amount = int(raw)
    data = await state.get_data()
    await state.update_data(transfer_amount=amount)
    await answer(
        message,
        T.WALLET_SEND_CONFIRM.format(amount=toman(amount), to_user=data.get("transfer_to")),
        reply_markup=K.stack(
            [
                [K.btn(T.BTN_WALLET_SEND_GO, WalletCB(action="send_go", ref="-"), style=K.YES)],
                [K.btn(T.BTN_CANCEL, NavCB(to="wallet"))],
            ]
        ),
    )


@router.callback_query(WalletCB.filter(F.action == "send_go"))
async def on_send_go(
    query: CallbackQuery, state: FSMContext, scope: Any = None, user: Any = None
) -> None:
    data = await state.get_data()
    await state.set_state(Wallet.idle)
    to_user, amount = data.get("transfer_to"), data.get("transfer_amount")
    if user is None or scope is None or not isinstance(to_user, int) or not isinstance(amount, int):
        await toast(query, T.ERR_GENERIC, alert=True)
        return
    await toast(query)
    sender = user.telegram_id

    def work(sync: Any) -> None:
        sync.wallet_transfers.transfer(from_user=sender, to_user=to_user, amount_toman=amount)

    try:
        await scope.in_shop(work)
    except Exception as failure:
        if not isinstance(failure, DomainError):
            logger.exception("bot.wallet_transfer_failed", user_id=sender)
        await safe_edit(
            query,
            customer_message(failure),
            markup=K.single(K.btn(T.BTN_BACK, NavCB(to="wallet"))),
        )
        return
    await safe_edit(
        query,
        T.WALLET_SENT.format(amount=toman(amount), to_user=to_user),
        markup=K.single(K.btn(T.BTN_BACK, NavCB(to="wallet"))),
    )


async def topup_limits(scope: Any) -> tuple[int, int]:
    """The shop's top-up range; the wallet's own bounds when it cannot be read."""
    service = getattr(scope, "settings_service", None)
    if service is None:
        return MIN_TOPUP, MAX_TOPUP
    try:
        return await service.get(TOPUP_MIN_TOMAN), await service.get(TOPUP_MAX_TOMAN)
    except Exception:
        logger.warning("wallet.topup_limits_unreadable", exc_info=True)
        return MIN_TOPUP, MAX_TOPUP


@router.callback_query(WalletCB.filter(F.action == "topup"))
async def on_topup(query: CallbackQuery, state: FSMContext, scope: Any = None) -> None:
    await toast(query)
    await state.set_state(Wallet.entering_amount)
    low, high = await topup_limits(scope)
    body = T.WALLET_ASK_AMOUNT.format(min_amount=toman(low), max_amount=toman(high))
    await safe_edit(query, body, markup=_preset_keyboard(low, high))


@router.callback_query(WalletCB.filter(F.action == "amount"))
async def on_preset(
    query: CallbackQuery,
    callback_data: WalletCB,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
) -> None:
    await toast(query)
    await state.update_data(amount=int(callback_data.ref))
    await state.set_state(Wallet.choosing_method)
    body = f"{T.PAY_CHOOSE}\n\n{T.LBL_TOTAL}: <b>{toman(int(callback_data.ref))}</b>"
    methods = await services.checkout.methods(user.id if user is not None else None)
    if not methods:
        await safe_edit(query, T.PAY_NO_METHODS, markup=K.single(K.home_button()))
        return
    await safe_edit(query, body, markup=_method_keyboard(methods))


@router.message(Wallet.entering_amount, F.text)
async def on_amount_text(
    message: Message,
    state: FSMContext,
    services: BotServices,
    scope: Any = None,
    user: Any = None,
) -> None:
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
    low, high = await topup_limits(scope)
    if amount < low:
        await answer(message, T.WALLET_AMOUNT_TOO_LOW.format(min_amount=toman(low)))
        return
    if amount > high:
        await answer(message, T.WALLET_AMOUNT_TOO_HIGH.format(max_amount=toman(high)))
        return

    await state.update_data(amount=amount)
    await state.set_state(Wallet.choosing_method)
    body = f"{T.PAY_CHOOSE}\n\n{T.LBL_TOTAL}: <b>{toman(amount)}</b>"
    methods = await services.checkout.methods(user.id if user is not None else None)
    if not methods:
        await answer(message, T.PAY_NO_METHODS, reply_markup=K.main_menu())
        return
    await answer(message, body, reply_markup=_method_keyboard(methods))


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

    if isinstance(details, GatewayScreen):
        # An online provider draws its own screen and settles by itself, so
        # there is no receipt to wait for and no state to keep.
        await state.clear()
        rows = [[K.url_btn(T.BTN_PAY_ONLINE, details.url)]] if details.url else []
        await safe_edit(
            query,
            details.body_fa or T.PAY_GATEWAY_READY,
            markup=K.stack(rows, home=True),
        )
        return

    payment = details.payment
    if payment is None:
        await safe_edit(query, T.ERR_GENERIC, markup=K.single(K.home_button()))
        return
    await state.update_data(payment_id=str(payment.payment_id))

    if isinstance(details, CardPaymentDetails):
        await state.set_state(Wallet.awaiting_receipt)
        body = _card_body(details, amount=payment.amount)
        # The same copy buttons as a purchase. Somebody topping up is holding
        # the same banking app open as somebody buying, and the digits are just
        # as easy to clip.
        markup = card_keyboard(details, amount=payment.amount, cancel_to="wallet")
    else:
        await state.set_state(Wallet.awaiting_crypto_txid)
        body = _crypto_body(details, amount=payment.amount)
        markup = K.single(K.btn(T.BTN_CANCEL, NavCB(to="wallet"), style=K.NO))

    await safe_edit(query, body, markup=markup)


@router.callback_query(WalletCB.filter(F.action == "method"))
async def on_topup_method(
    query: CallbackQuery,
    callback_data: WalletCB,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
) -> None:
    await toast(query)
    if user is not None:
        await _begin_topup(query, state, services, user, callback_data.ref)


@router.message(Wallet.awaiting_receipt, F.photo)
async def on_topup_receipt(
    message: Message,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
    **kwargs: Any,
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
    await S.send(kwargs.get("bot"), message.chat.id, kwargs.get("stickers"), "receipt")
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
