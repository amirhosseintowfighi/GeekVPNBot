"""Checkout: review -> optional coupon -> payment method -> proof.

Three payment rails, deliberately different in shape:

* **Wallet** is synchronous. Balance is sufficient, service provisions now.
* **Card-to-card** is asynchronous and manual. We show the destination card,
  take a receipt photo, and park the payment in `PENDING_REVIEW` for an admin.
* **Crypto** is asynchronous. We show an address and take a TxID.

A bank gateway is intentionally absent. `CheckoutService` is the seam it will
plug into later -- adding it means one new `begin_*` method and one new
button, with no change to this flow's structure.

The selected plan id is held in FSM state, but the *price* is never trusted
from state: it is re-quoted immediately before the payment intent is created.
A customer must not be able to sit on a review screen through the end of a
flash sale and still pay the sale price.
"""

from __future__ import annotations

import uuid
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from geekvpn.application.bot.read_models import (
    CardPaymentDetails,
    CryptoPaymentDetails,
)
from geekvpn.application.bot.services import BotServices
from geekvpn.application.catalog.dto import PlanView, ProductView
from geekvpn.application.payments.adapters import CARD_STATED_WINDOW
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.bot.handlers.common import (
    answer,
    customer_message,
    match_ref,
    safe_edit,
    tier_of,
    toast,
)
from geekvpn.presentation.bot.handlers.shop import load_storefront
from geekvpn.presentation.bot.states import Purchase
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import render as R
from geekvpn.presentation.bot.ui import stickers as S
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB, PayCB, ShopCB
from geekvpn.presentation.bot.ui.fa import fa_relative, normalize_input, toman

logger = get_logger("bot.purchase")

router = Router(name="purchase")

MIN_TXID = 10


def _review_keyboard(*, has_coupon: bool) -> InlineKeyboardMarkup:
    rows: list[list[Any]] = [
        [K.btn(T.BTN_PAY, PayCB(action="choose", method="-", ref="-"), style=K.GO)]
    ]
    if has_coupon:
        rows.append([K.btn(T.BTN_DROP_COUPON, PayCB(action="uncoupon", method="-", ref="-"))])
    else:
        rows.append([K.btn(T.BTN_APPLY_COUPON, PayCB(action="coupon", method="-", ref="-"))])
    rows.append([K.btn(T.BTN_BACK, NavCB(to="shop")), K.home_button()])
    return K.stack(rows)


def _method_keyboard(*, wallet_ok: bool) -> InlineKeyboardMarkup:
    rows: list[list[Any]] = []
    if wallet_ok:
        # Green: the balance is already ours, so this one completes on the
        # spot rather than sending the customer off to transfer money.
        rows.append(
            [K.btn(T.PAY_WALLET, PayCB(action="pay", method="wallet", ref="-"), style=K.YES)]
        )
    # Both blue: this is a choice between two equals, and leaving one grey
    # reads as "not this one" rather than "either is fine".
    rows.append(
        [K.btn(T.PAY_CARD, PayCB(action="pay", method="card", ref="-"), style=K.GO)]
    )
    rows.append(
        [K.btn(T.PAY_CRYPTO, PayCB(action="pay", method="crypto", ref="-"), style=K.GO)]
    )
    rows.append([K.btn(T.BTN_CANCEL, NavCB(to="home"), style=K.NO)])
    return K.stack(rows)


async def _find_plan(
    *, plan_id: uuid.UUID, user: Any, scope: Any, services: Any
) -> tuple[PlanView | None, ProductView | None]:
    """The selected package and the product it belongs to.

    Typed, unlike almost everything else that crosses this file. `Any` here
    cost a working checkout: the review screen read `plan.name_fa`, which
    `PlanView` does not have - the catalogue *model* has it, and so does
    `ServerStatusRow` - and mypy could not see the mistake through an `Any`.
    Every customer who picked a package got the generic apology.
    """
    view = await load_storefront(user=user, scope=scope, services=services)
    for category in view.categories:
        for product in category.products:
            for plan in product.plans:
                if plan.id == plan_id:
                    return plan, product
    return None, None


async def _render_review(
    *,
    query: CallbackQuery,
    state: FSMContext,
    user: Any,
    scope: Any,
    services: Any,
) -> None:
    """Re-quote the selected plan and redraw the review screen."""
    data = await state.get_data()
    plan_id = data.get("plan_id")
    coupon = data.get("coupon")
    if not plan_id:
        await safe_edit(query, T.ERR_SESSION_EXPIRED, markup=K.single(K.home_button()))
        return

    plan, product = await _find_plan(
        plan_id=uuid.UUID(str(plan_id)), user=user, scope=scope, services=services
    )
    if plan is None or product is None:
        await safe_edit(query, T.PLAN_UNAVAILABLE, markup=K.single(K.home_button()))
        return

    snapshot = await services.wallet.snapshot(user.id)
    try:
        quote = await scope.quoting.quote_view(
            plan_id=plan.id,
            user_id=user.id,
            coupon_code=coupon,
            loyalty_tier=tier_of(snapshot.lifetime_spend),
        )
    except Exception:
        # A coupon that validated a moment ago can expire mid-flow. Drop it
        # and re-quote clean rather than dead-ending the purchase.
        #
        # Logged even though it is recovered: this also catches a quoting
        # failure that has nothing to do with coupons, and silently re-quoting
        # one of those hides a pricing bug behind a working screen.
        logger.warning("bot.requote_without_coupon", exc_info=True)
        await state.update_data(coupon=None)
        quote = await scope.quoting.quote_view(
            plan_id=plan.id,
            user_id=user.id,
            loyalty_tier=tier_of(snapshot.lifetime_spend),
        )
        coupon = None

    name = f"{product.name} \u2014 {plan.name}"
    await state.update_data(total=quote.total, plan_name=name)
    await state.set_state(Purchase.reviewing)
    await safe_edit(
        query,
        # The whole package, not just its price. This screen used to be the
        # breakdown alone, so a customer confirming a purchase could not see
        # the volume, the duration, the device count or a single one of the
        # features the operator wrote - they were on the previous screen and
        # disappeared the moment a package was picked.
        R.plan_detail(
            plan,
            product_name=product.name,
            quote=quote,
            features=product.features,
        ),
        markup=_review_keyboard(has_coupon=bool(coupon)),
    )


@router.callback_query(ShopCB.filter(F.action == "plan"))
async def on_select_plan(
    query: CallbackQuery,
    callback_data: ShopCB,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
    scope: Any = None,
) -> None:
    await toast(query)
    if user is None or scope is None:
        return
    view = await load_storefront(user=user, scope=scope, services=services)
    found = None
    for category in view.categories:
        for product in category.products:
            candidate = match_ref(list(product.plans), callback_data.ref, "id")
            if candidate is not None:
                found = candidate
                break
        if found:
            break
    if found is None:
        await safe_edit(query, T.ERR_STALE_BUTTON, markup=K.single(K.home_button()))
        return
    await state.update_data(plan_id=str(found.id), coupon=None)
    await _render_review(query=query, state=state, user=user, scope=scope, services=services)


@router.callback_query(PayCB.filter(F.action == "coupon"))
async def on_ask_coupon(query: CallbackQuery, state: FSMContext) -> None:
    await toast(query)
    await state.set_state(Purchase.entering_coupon)
    await safe_edit(query, T.ASK_COUPON, markup=K.single(K.btn(T.BTN_CANCEL, NavCB(to="review"), style=K.NO)))


@router.callback_query(PayCB.filter(F.action == "uncoupon"))
async def on_drop_coupon(
    query: CallbackQuery,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
    scope: Any = None,
) -> None:
    await toast(query, T.COUPON_REMOVED)
    await state.update_data(coupon=None)
    if user and scope:
        await _render_review(query=query, state=state, user=user, scope=scope, services=services)


@router.callback_query(NavCB.filter(F.to == "review"))
async def on_back_to_review(
    query: CallbackQuery,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
    scope: Any = None,
) -> None:
    await toast(query)
    if user and scope:
        await _render_review(query=query, state=state, user=user, scope=scope, services=services)


@router.message(Purchase.entering_coupon, F.text)
async def on_coupon_text(
    message: Message,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
    scope: Any = None,
) -> None:
    """Validate a typed coupon.

    `preview_coupon` reports rejection as data with a Persian reason, so the
    customer is told *why* the code failed rather than a flat "invalid".
    """
    if user is None or scope is None:
        await answer(message, T.ERR_GENERIC)
        return

    data = await state.get_data()
    plan_id = data.get("plan_id")
    if not plan_id:
        await answer(message, T.ERR_SESSION_EXPIRED)
        await state.clear()
        return

    code = normalize_input(message.text or "").upper()
    snapshot = await services.wallet.snapshot(user.id)
    preview = await scope.quoting.preview_coupon(
        plan_id=uuid.UUID(str(plan_id)),
        code=code,
        user_id=user.id,
        loyalty_tier=tier_of(snapshot.lifetime_spend),
    )

    if not preview.is_valid:
        await answer(message, f"\u274c {preview.message_fa}")
        return

    await state.update_data(coupon=preview.code)
    await state.set_state(Purchase.reviewing)
    await answer(
        message,
        T.COUPON_APPLIED.format(code=preview.code, amount=toman(preview.discount)),
    )

    plan, product = await _find_plan(
        plan_id=uuid.UUID(str(plan_id)), user=user, scope=scope, services=services
    )
    if plan is None or product is None:
        return
    quote = await scope.quoting.quote_view(
        plan_id=plan.id,
        user_id=user.id,
        coupon_code=preview.code,
        loyalty_tier=tier_of(snapshot.lifetime_spend),
    )
    name = f"{product.name} \u2014 {plan.name}"
    await state.update_data(total=quote.total, plan_name=name)
    await answer(
        message,
        R.quote_breakdown(quote, plan_name=name),
        reply_markup=_review_keyboard(has_coupon=True),
    )


@router.callback_query(PayCB.filter(F.action == "choose"))
async def on_choose_method(
    query: CallbackQuery,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
) -> None:
    await toast(query)
    if user is None:
        return
    data = await state.get_data()
    total = int(data.get("total") or 0)
    snapshot = await services.wallet.snapshot(user.id)
    wallet_ok = snapshot.balance >= total > 0

    body = f"{T.PAY_CHOOSE}\n\n{T.LBL_TOTAL}: <b>{toman(total)}</b>"
    if not wallet_ok and total:
        body += "\n\n" + T.PAY_WALLET_SHORT.format(
            balance=toman(snapshot.balance),
            needed=toman(total),
            shortfall=toman(max(0, total - snapshot.balance)),
        )
    await state.set_state(Purchase.choosing_payment)
    await safe_edit(query, body, markup=_method_keyboard(wallet_ok=wallet_ok))


@router.callback_query(PayCB.filter(F.action == "pay"))
async def on_pay(
    query: CallbackQuery,
    callback_data: PayCB,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
    **kwargs: Any,
) -> None:
    await toast(query)
    if user is None:
        return

    data = await state.get_data()
    plan_id = data.get("plan_id")
    coupon = data.get("coupon")
    if not plan_id:
        await safe_edit(query, T.ERR_SESSION_EXPIRED, markup=K.single(K.home_button()))
        return

    plan_uuid = uuid.UUID(str(plan_id))
    method = callback_data.method

    try:
        if method == "wallet":
            await services.checkout.pay_from_wallet(
                user_id=user.id, plan_id=plan_uuid, coupon_code=coupon
            )
            await state.clear()
            cashback = data.get("cashback") or 0
            # A wallet purchase settles immediately, so the amount shown is the
            # quote the customer just confirmed rather than a payment record.
            await safe_edit(
                query,
                T.PAY_SUCCESS.format(
                    plan=data.get("plan_name", ""),
                    amount=toman(int(data.get("total") or 0)),
                    cashback_line=(
                        T.PAY_CASHBACK_LINE.format(amount=toman(cashback)) if cashback else ""
                    ),
                ),
                markup=K.single(
                    K.btn(T.MENU_DASHBOARD, NavCB(to="dashboard"), style=K.YES)
                ),
            )
            # The one moment in the bot worth celebrating, and the only
            # `SECTION_EMOJI` entry nothing sent. Sent after the screen rather
            # than before it, unlike every other section: this one is not
            # navigation, it is applause for something that just happened.
            await S.send(
                kwargs.get("bot"),
                query.message.chat.id if query.message else user.id,
                kwargs.get("stickers"),
                "delivered",
            )
            return

        if method == "card":
            details = await services.checkout.begin_card(
                user_id=user.id, plan_id=plan_uuid, coupon_code=coupon
            )
            if details.payment is None:
                await safe_edit(query, T.ERR_GENERIC, markup=K.single(K.home_button()))
                return
            await state.update_data(payment_id=str(details.payment.payment_id))
            await state.set_state(Purchase.awaiting_receipt)
            await safe_edit(
                query,
                _card_body(details, amount=details.payment.amount),
                markup=card_keyboard(details, amount=details.payment.amount),
            )
            return

        if method == "crypto":
            crypto = await services.checkout.begin_crypto(
                user_id=user.id, plan_id=plan_uuid, coupon_code=coupon
            )
            if crypto.payment is None:
                await safe_edit(query, T.ERR_GENERIC, markup=K.single(K.home_button()))
                return
            await state.update_data(payment_id=str(crypto.payment.payment_id))
            await state.set_state(Purchase.awaiting_crypto_txid)
            await safe_edit(
                query,
                _crypto_body(crypto, amount=crypto.payment.amount),
                markup=K.single(K.btn(T.BTN_CANCEL, NavCB(to="home"), style=K.NO)),
            )
            return

        await safe_edit(query, T.PAY_GATEWAY_SOON, markup=K.single(K.home_button()))
    except Exception as failure:
        # Logged, not merely apologised for. This `except` used to swallow the
        # exception whole: no traceback, no `handler_failed`, nothing in the
        # log at all - so a wallet purchase that debited a customer and
        # delivered nothing left no evidence of what went wrong, and every
        # attempt to diagnose it from the outside came back empty.
        logger.exception("bot.payment_failed", method=method, plan_id=str(plan_uuid))
        await safe_edit(query, customer_message(failure), markup=K.single(K.home_button()))


def card_keyboard(
    details: CardPaymentDetails, *, amount: int, cancel_to: str = "home"
) -> InlineKeyboardMarkup:
    """Two taps instead of two drag handles.

    A customer reading this screen has to get a sixteen-digit card number and
    an unrounded amount into a banking app. Long-pressing a `<code>` block and
    dragging a selection over either of them is where digits get lost - and the
    three that identify the transfer are the last three, the easiest to clip.

    Copy buttons carry the value client-side, so neither depends on the bot
    answering quickly while somebody has their bank open.
    """
    return K.stack(
        [
            [K.copy_btn(T.BTN_COPY_CARD, details.card_number, style=K.YES)],
            # Latin digits, no separators: this is pasted into an amount field.
            [K.copy_btn(T.BTN_COPY_AMOUNT, str(amount), style=K.GO)],
            [K.btn(T.BTN_CANCEL, NavCB(to=cancel_to), style=K.NO)],
        ]
    )


def _card_body(details: CardPaymentDetails, *, amount: int) -> str:
    return T.PAY_CARD_INSTRUCTIONS.format(
        amount=f"<b>{toman(amount)}</b>",
        # Latin digits, no separators, nothing but the number: this one is for
        # tapping to copy and pasting straight into a banking app, which is
        # what stops a customer retyping it and dropping the last three digits
        # that identify their receipt.
        amount_plain=amount,
        card_number=details.card_number,
        card_holder=details.card_holder_fa,
        bank=details.bank_fa,
        # The stated window, not the enforced one. They differ on purpose:
        # `CARD_WINDOW` is longer, so a customer who transfers just before the
        # deadline and photographs the receipt just after does not lose money
        # to a promise we had no reason to keep to the second.
        window=fa_relative(CARD_STATED_WINDOW),
        sla=details.review_sla_fa,
    )


def _crypto_body(details: CryptoPaymentDetails, *, amount: int) -> str:
    return T.PAY_CRYPTO_INSTRUCTIONS.format(
        amount=f"<b>{toman(amount)}</b>",
        network=details.network,
        asset=details.asset,
        crypto_amount=f"<code>{details.amount_display}</code>",
        address=f"<code>{details.address}</code>",
    )


@router.message(Purchase.awaiting_receipt, F.photo)
async def on_receipt_photo(
    message: Message,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
    **kwargs: Any,
) -> None:
    """Accept the card-to-card receipt image.

    `photo[-1]` is the highest resolution Telegram kept -- an admin needs to
    read a reference number off it.
    """
    data = await state.get_data()
    payment_id = data.get("payment_id")
    if not payment_id or not message.photo:
        await answer(message, T.ERR_SESSION_EXPIRED)
        await state.clear()
        return

    if user is None:
        await answer(message, T.ERR_SESSION_EXPIRED)
        await state.clear()
        return

    file_id = message.photo[-1].file_id
    payment = await services.checkout.attach_receipt(
        user.id, payment_id=uuid.UUID(str(payment_id)), file_id=file_id
    )
    await state.clear()
    await S.send(kwargs.get("bot"), message.chat.id, kwargs.get("stickers"), "receipt")
    await answer(
        message,
        T.PAY_RECEIPT_RECEIVED.format(ref=f"<code>{payment.reference}</code>"),
        reply_markup=K.main_menu(),
    )


@router.message(Purchase.awaiting_receipt)
async def on_receipt_not_photo(message: Message) -> None:
    await answer(message, T.PAY_RECEIPT_NOT_IMAGE)


@router.message(Purchase.awaiting_crypto_txid, F.text)
async def on_txid(
    message: Message,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
) -> None:
    data = await state.get_data()
    payment_id = data.get("payment_id")
    if not payment_id or user is None:
        await answer(message, T.ERR_SESSION_EXPIRED)
        await state.clear()
        return

    txid = normalize_input(message.text or "")
    if len(txid) < MIN_TXID or " " in txid:
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
