"""The operator's area, inside the bot.

Approving a receipt and answering a ticket are the two things that keep a
customer waiting, and both lived only in a browser. An operator away from a
desk could see the Telegram notification that a receipt had arrived and could
do nothing about it, which is the gap this closes.

Nothing here is a second implementation. Every action calls the same service
the admin panel calls - `PaymentReviewService`, `TicketService`, `ManageAdmins`
- so a receipt approved from a phone and one approved from the panel take the
same path, publish the same events, and land in the same audit log.

Access is the admin record's own `telegram_id`. There is no separate list of
"bot admins" to fall out of step with the real one, and a Telegram id is
established by the update itself rather than typed in by the person using it.
"""

from __future__ import annotations

import secrets
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from geekvpn.application.payments.review_service import ApprovalRequest
from geekvpn.application.support.ticket_service import ReplyRequest
from geekvpn.domain.base.errors import DomainError
from geekvpn.domain.identity.admin import Admin
from geekvpn.domain.identity.enums import UserStatus
from geekvpn.domain.identity.permissions import AdminRole
from geekvpn.domain.notifications.enums import NotificationCategory
from geekvpn.domain.notifications.message import RenderedMessage
from geekvpn.domain.panels.errors import PanelError
from geekvpn.domain.payments.enums import PaymentState
from geekvpn.domain.provisioning.enums import OrderState, SubscriptionState
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.di.sync_scope import SyncScope
from geekvpn.presentation.api.admin_common import mutate_scope, read_scope
from geekvpn.presentation.api.routers.admin_analytics import run_report
from geekvpn.presentation.bot.handlers.common import answer, safe_edit, toast
from geekvpn.presentation.bot.ui import admin_text as A
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui.callbacks import AdminCB
from geekvpn.presentation.bot.ui.fa import fa_digits, normalize_input, toman

router = Router(name="admin")

#: A queue longer than this is a staffing problem, not a pagination problem.
QUEUE_LIMIT = 10

#: Roles offerable from the bot. `SUPER_ADMIN` is deliberately absent: handing
#: out the role that can hand out roles belongs somewhere with an audit trail
#: an operator cannot scroll past.
OFFERABLE_ROLES: tuple[AdminRole, ...] = (
    AdminRole.ADMIN,
    AdminRole.FINANCE,
    AdminRole.SUPPORT,
    AdminRole.VIEWER,
)

ROLE_LABEL_FA: dict[AdminRole, str] = {
    AdminRole.SUPER_ADMIN: "مدیر ارشد",
    AdminRole.ADMIN: "مدیر",
    AdminRole.FINANCE: "مالی",
    AdminRole.SUPPORT: "پشتیبانی",
    AdminRole.VIEWER: "فقط مشاهده",
}


class AdminFlow(StatesGroup):
    rejecting_payment = State()
    replying_to_ticket = State()
    adding_admin_id = State()
    finding_customer = State()
    wallet_amount = State()
    wallet_reason = State()
    messaging_customer = State()
    suspending_customer = State()
    subscription_days = State()
    subscription_gib = State()
    subscription_reason = State()


# -- access ----------------------------------------------------------------


async def current_admin(scope: Any, user: Any) -> Admin | None:
    """The admin record behind this Telegram account, if there is one."""
    if user is None or scope is None:
        return None
    found: Admin | None = await scope.admins.get_by_telegram_id(user.telegram_id)
    return found


async def is_admin(scope: Any, user: Any) -> bool:
    """Whether to *show* the operator entry on the home screen.

    Not access control - every handler behind that button checks again on each
    call. This only decides whether an operator has to be told a command
    exists before they can run the business from their phone.
    """
    return await _guard(scope, user) is not None


async def _guard(scope: Any, user: Any) -> Admin | None:
    admin = await current_admin(scope, user)
    # `can_authenticate` rather than a plain "not disabled": a suspended or
    # locked admin must lose the bot at the same moment they lose the panel.
    if admin is None or not admin.status.can_authenticate:
        return None
    return admin


# -- entry point -----------------------------------------------------------


def _menu() -> InlineKeyboardMarkup:
    return K.stack(
        [
            # The two queues with a customer waiting come first, and carry the
            # only colour on this screen for the same reason.
            [K.btn(A.BTN_PAYMENTS, AdminCB(action="payments"), style=K.YES)],
            [K.btn(A.BTN_TICKETS, AdminCB(action="tickets"), style=K.GO)],
            [K.btn(A.BTN_CUSTOMER, AdminCB(action="find"))],
            [K.btn(A.BTN_ORDERS, AdminCB(action="orders"))],
            [K.btn(A.BTN_STATS, AdminCB(action="stats"))],
            [K.btn(A.BTN_ADMINS, AdminCB(action="admins"))],
        ]
    )


@router.message(Command("admin"))
async def on_admin_command(
    message: Message, state: FSMContext, scope: Any = None, user: Any = None
) -> None:
    await state.clear()
    if await _guard(scope, user) is None:
        await answer(message, A.NOT_AN_ADMIN)
        return
    await answer(message, A.MENU_TITLE, reply_markup=_menu())


@router.callback_query(AdminCB.filter(F.action == "menu"))
async def on_menu(query: CallbackQuery, state: FSMContext, **_: Any) -> None:
    await state.clear()
    await safe_edit(query, A.MENU_TITLE, markup=_menu())


# -- payments --------------------------------------------------------------


@router.callback_query(AdminCB.filter(F.action == "payments"))
async def on_payments(
    query: CallbackQuery, container: Container, scope: Any = None, user: Any = None
) -> None:
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return

    def work(sync: SyncScope) -> list[Any]:
        return list(sync.payments.in_state(PaymentState.PENDING_REVIEW, limit=QUEUE_LIMIT))

    payments = await read_scope(container, work)
    if not payments:
        await safe_edit(query, A.PAYMENTS_EMPTY, markup=_back())
        return

    rows = [
        [
            K.btn(
                f"{toman(payment.amount.amount)} — {fa_digits(str(payment.user_id))}",
                AdminCB(action="payment", ref=payment.id),
            )
        ]
        for payment in payments
    ]
    rows.append([K.btn(A.BTN_BACK, AdminCB(action="menu"))])
    await safe_edit(query, A.PAYMENTS_TITLE, markup=K.stack(rows))


@router.callback_query(AdminCB.filter(F.action == "payment"))
async def on_payment(
    query: CallbackQuery,
    callback_data: AdminCB,
    container: Container,
    scope: Any = None,
    user: Any = None,
) -> None:
    """The receipt image itself, as a new message.

    Sent rather than edited in: an image cannot replace the text of the card it
    belongs to, and a reviewer wants both on screen at once.
    """
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return

    payment_id = callback_data.ref

    def work(sync: SyncScope) -> Any:
        return sync.payments.get(payment_id)

    payment = await read_scope(container, work)
    if payment is None or query.message is None:
        await toast(query, A.PAYMENTS_EMPTY, alert=True)
        return

    body = A.PAYMENT_CARD.format(
        amount=toman(payment.amount.amount),
        user_id=fa_digits(str(payment.user_id)),
        reference=payment.id,
        created=fa_digits(payment.created_at.strftime("%Y-%m-%d %H:%M")),
    )
    markup = K.stack(
        [
            [
                # Green and red, because these two are one tap apart and one of
                # them moves money. Colour is the cheapest way to make a
                # mis-tap look wrong before it happens.
                K.btn(A.BTN_APPROVE, AdminCB(action="approve", ref=payment_id), style=K.YES),
                K.btn(A.BTN_REJECT, AdminCB(action="reject", ref=payment_id), style=K.NO),
            ],
            [K.btn(A.BTN_BACK, AdminCB(action="payments"))],
        ]
    )

    file_id = getattr(payment.proof, "file_id", None) if payment.proof else None
    if file_id:
        await query.message.answer_photo(file_id, caption=body, reply_markup=markup)
        await toast(query)
    else:
        await safe_edit(query, body + "\n\n" + A.PAYMENT_NO_IMAGE, markup=markup)


@router.callback_query(AdminCB.filter(F.action == "approve"))
async def on_approve(
    query: CallbackQuery,
    callback_data: AdminCB,
    container: Container,
    scope: Any = None,
    user: Any = None,
) -> None:
    admin = await _guard(scope, user)
    if admin is None or user is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return

    payment_id = callback_data.ref
    actor = user.telegram_id

    def work(sync: SyncScope) -> None:
        sync.review.approve(ApprovalRequest(payment_id=payment_id, actor_id=actor))

    try:
        await mutate_scope(container, work)
    except DomainError as failure:
        await toast(query, A.ACTION_FAILED.format(reason=str(failure)), alert=True)
        return

    await toast(query, A.PAYMENT_APPROVED, alert=True)
    await safe_edit(query, A.PAYMENT_APPROVED, markup=_back("payments"))


@router.callback_query(AdminCB.filter(F.action == "reject"))
async def on_reject(
    query: CallbackQuery, callback_data: AdminCB, state: FSMContext, **_: Any
) -> None:
    await state.update_data(payment_id=callback_data.ref)
    await state.set_state(AdminFlow.rejecting_payment)
    await safe_edit(query, A.PAYMENT_ASK_REASON, markup=_back("payments"))


@router.message(AdminFlow.rejecting_payment, F.text)
async def on_reject_reason(
    message: Message,
    state: FSMContext,
    container: Container,
    scope: Any = None,
    user: Any = None,
) -> None:
    if await _guard(scope, user) is None or user is None:
        await answer(message, A.NOT_AN_ADMIN)
        await state.clear()
        return

    data = await state.get_data()
    payment_id = str(data.get("payment_id") or "")
    reason = (message.text or "").strip()
    actor = user.telegram_id

    def work(sync: SyncScope) -> None:
        sync.review.reject(payment_id=payment_id, actor_id=actor, reason_fa=reason)

    try:
        await mutate_scope(container, work)
    except DomainError as failure:
        await answer(message, A.ACTION_FAILED.format(reason=str(failure)))
        return
    finally:
        await state.clear()

    await answer(message, A.PAYMENT_REJECTED, reply_markup=K.main_menu())


# -- tickets ---------------------------------------------------------------


@router.callback_query(AdminCB.filter(F.action == "tickets"))
async def on_tickets(
    query: CallbackQuery, container: Container, scope: Any = None, user: Any = None
) -> None:
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return

    def work(sync: SyncScope) -> list[Any]:
        return sync.support.queue(limit=QUEUE_LIMIT)

    tickets = await read_scope(container, work)
    if not tickets:
        await safe_edit(query, A.TICKETS_EMPTY, markup=_back())
        return

    rows = [
        [K.btn(ticket.subject_fa[:40] or ticket.reference, AdminCB(action="ticket", ref=ticket.ticket_id))]
        for ticket in tickets
    ]
    rows.append([K.btn(A.BTN_BACK, AdminCB(action="menu"))])
    await safe_edit(query, A.TICKETS_TITLE, markup=K.stack(rows))


@router.callback_query(AdminCB.filter(F.action == "ticket"))
async def on_ticket(
    query: CallbackQuery,
    callback_data: AdminCB,
    container: Container,
    scope: Any = None,
    user: Any = None,
) -> None:
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return

    ticket_id = callback_data.ref

    def work(sync: SyncScope) -> tuple[Any, list[Any]]:
        return sync.support.get_ticket(ticket_id), sync.support.get_messages(ticket_id)

    try:
        summary, messages = await read_scope(container, work)
    except DomainError:
        await toast(query, A.TICKETS_EMPTY, alert=True)
        return

    thread = "\n\n".join(
        f"<b>{'پشتیبانی' if m.kind.value == 'agent' else 'کاربر'}:</b> {m.body_fa}"
        for m in messages[-6:]
    )
    body = A.TICKET_CARD.format(
        subject=summary.subject_fa,
        reference=summary.reference,
        user_id=fa_digits(str(summary.user_id)),
        state=summary.state.value,
        thread=thread,
    )
    await safe_edit(
        query,
        body,
        markup=K.stack(
            [
                [
                    K.btn(A.BTN_REPLY, AdminCB(action="reply", ref=ticket_id), style=K.GO),
                    K.btn(
                        A.BTN_CLOSE_TICKET, AdminCB(action="close", ref=ticket_id), style=K.NO
                    ),
                ],
                [K.btn(A.BTN_BACK, AdminCB(action="tickets"))],
            ]
        ),
    )


@router.callback_query(AdminCB.filter(F.action == "reply"))
async def on_reply(
    query: CallbackQuery, callback_data: AdminCB, state: FSMContext, **_: Any
) -> None:
    await state.update_data(ticket_id=callback_data.ref)
    await state.set_state(AdminFlow.replying_to_ticket)
    await safe_edit(query, A.TICKET_ASK_REPLY, markup=_back("tickets"))


@router.message(AdminFlow.replying_to_ticket, F.text)
async def on_reply_text(
    message: Message,
    state: FSMContext,
    container: Container,
    scope: Any = None,
    user: Any = None,
) -> None:
    if await _guard(scope, user) is None or user is None:
        await answer(message, A.NOT_AN_ADMIN)
        await state.clear()
        return

    data = await state.get_data()
    ticket_id = str(data.get("ticket_id") or "")
    body = (message.text or "").strip()
    actor = user.telegram_id

    def work(sync: SyncScope) -> None:
        sync.support.agent_reply(
            ReplyRequest(ticket_id=ticket_id, body_fa=body, author_id=actor)
        )

    try:
        await mutate_scope(container, work)
    except DomainError as failure:
        await answer(message, A.ACTION_FAILED.format(reason=str(failure)))
        return
    finally:
        await state.clear()

    await answer(message, A.TICKET_REPLIED, reply_markup=K.main_menu())


@router.callback_query(AdminCB.filter(F.action == "close"))
async def on_close_ticket(
    query: CallbackQuery,
    callback_data: AdminCB,
    container: Container,
    scope: Any = None,
    user: Any = None,
) -> None:
    if await _guard(scope, user) is None or user is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return

    ticket_id = callback_data.ref
    actor = user.telegram_id

    def work(sync: SyncScope) -> None:
        sync.support.close_ticket(ticket_id, actor_id=actor, closed_by_agent=True)

    try:
        await mutate_scope(container, work)
    except DomainError as failure:
        await toast(query, A.ACTION_FAILED.format(reason=str(failure)), alert=True)
        return

    await safe_edit(query, A.TICKET_CLOSED, markup=_back("tickets"))


# -- admins ----------------------------------------------------------------


@router.callback_query(AdminCB.filter(F.action == "admins"))
async def on_admins(query: CallbackQuery, scope: Any = None, user: Any = None) -> None:
    admin = await _guard(scope, user)
    if admin is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return

    rows = [
        A.ADMINS_ROW.format(
            username=record.username,
            role=ROLE_LABEL_FA.get(record.role, record.role.value),
            telegram=" — 📱" if record.telegram_id else "",
        )
        for record in await scope.admins.list_all()
    ]
    buttons = []
    if admin.role is AdminRole.SUPER_ADMIN:
        buttons.append([K.btn(A.BTN_ADD_ADMIN, AdminCB(action="add_admin"))])
    buttons.append([K.btn(A.BTN_BACK, AdminCB(action="menu"))])

    await safe_edit(query, A.ADMINS_TITLE + "\n\n" + "\n".join(rows), markup=K.stack(buttons))


@router.callback_query(AdminCB.filter(F.action == "add_admin"))
async def on_add_admin(
    query: CallbackQuery, state: FSMContext, scope: Any = None, user: Any = None
) -> None:
    admin = await _guard(scope, user)
    if admin is None or admin.role is not AdminRole.SUPER_ADMIN:
        await toast(query, A.ONLY_SUPER_ADMIN, alert=True)
        return
    await state.set_state(AdminFlow.adding_admin_id)
    await safe_edit(query, A.ADD_ADMIN_ASK_ID, markup=_back("admins"))


@router.message(AdminFlow.adding_admin_id)
async def on_add_admin_id(
    message: Message, state: FSMContext, scope: Any = None, user: Any = None
) -> None:
    """A forwarded message or a typed id.

    Forwarding is offered first because it cannot be mistyped, and mistyping
    here grants access to somebody else's account.
    """
    admin = await _guard(scope, user)
    if admin is None or admin.role is not AdminRole.SUPER_ADMIN:
        await answer(message, A.ONLY_SUPER_ADMIN)
        await state.clear()
        return

    origin = getattr(message, "forward_from", None)
    if origin is not None:
        telegram_id = origin.id
    else:
        raw = (message.text or "").strip()
        if getattr(message, "forward_date", None) is not None and not raw.isdigit():
            await answer(message, A.ADD_ADMIN_HIDDEN_FORWARD)
            return
        if not raw.isdigit():
            await answer(message, A.ADD_ADMIN_BAD_ID)
            return
        telegram_id = int(raw)

    if await scope.admins.get_by_telegram_id(telegram_id) is not None:
        await answer(message, A.ADD_ADMIN_EXISTS)
        await state.clear()
        return

    await state.update_data(telegram_id=telegram_id)
    await answer(
        message,
        A.ADD_ADMIN_ASK_ROLE,
        reply_markup=K.stack(
            [
                [K.btn(ROLE_LABEL_FA[role], AdminCB(action="role", ref=role.value))]
                for role in OFFERABLE_ROLES
            ]
        ),
    )


@router.callback_query(AdminCB.filter(F.action == "role"), StateFilter(AdminFlow.adding_admin_id))
async def on_add_admin_role(
    query: CallbackQuery,
    callback_data: AdminCB,
    state: FSMContext,
    scope: Any = None,
    user: Any = None,
) -> None:
    """Creates the account with a password nobody ever sees.

    A password typed into a chat lives in that chat forever, on two devices
    and in Telegram's storage. The account works in the bot immediately, which
    is what an operator with a phone actually needs; panel sign-in requires
    setting a password from the panel, where it belongs.
    """
    admin = await _guard(scope, user)
    if admin is None or admin.role is not AdminRole.SUPER_ADMIN:
        await toast(query, A.ONLY_SUPER_ADMIN, alert=True)
        return

    data = await state.get_data()
    telegram_id = int(data.get("telegram_id") or 0)
    role = AdminRole(callback_data.ref)
    username = f"tg{telegram_id}"

    try:
        await scope.manage_admins.create(
            username=username,
            password=secrets.token_urlsafe(32),
            role=role,
            telegram_id=telegram_id,
            actor_id=admin.id,
        )
    except DomainError as failure:
        await toast(query, A.ACTION_FAILED.format(reason=str(failure)), alert=True)
        return
    finally:
        await state.clear()

    await safe_edit(
        query,
        A.ADD_ADMIN_DONE.format(username=username, role=ROLE_LABEL_FA[role]),
        markup=_back("admins"),
    )


# -- one customer ----------------------------------------------------------
#
# Everything an operator does about a person, from the person. The panel is
# organised by object - payments, orders, subscriptions - which is right at a
# desk with a wide screen. On a phone the question is always "this customer is
# messaging me, what is going on with them", so this screen answers that one.


@router.callback_query(AdminCB.filter(F.action == "find"))
async def on_find(
    query: CallbackQuery, state: FSMContext, scope: Any = None, user: Any = None
) -> None:
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return
    await state.set_state(AdminFlow.finding_customer)
    await safe_edit(query, A.CUSTOMER_ASK_ID, markup=_back())


@router.message(AdminFlow.finding_customer)
async def on_find_id(
    message: Message,
    state: FSMContext,
    container: Container,
    scope: Any = None,
    user: Any = None,
) -> None:
    if await _guard(scope, user) is None:
        await answer(message, A.NOT_AN_ADMIN)
        await state.clear()
        return

    telegram_id = _telegram_id_from(message)
    if telegram_id is None:
        await answer(message, A.ADD_ADMIN_BAD_ID)
        return

    await state.clear()
    card = await _customer_card(scope, container, telegram_id)
    if card is None:
        await answer(message, A.CUSTOMER_NOT_FOUND, reply_markup=K.main_menu())
        return
    body, markup = card
    await answer(message, body, reply_markup=markup)


async def _customer_card(
    scope: Any, container: Container, telegram_id: int
) -> tuple[str, InlineKeyboardMarkup] | None:
    """The person, their money, and what can be done about both."""
    customer = await scope.users.get_by_telegram_id(telegram_id)
    if customer is None:
        return None

    def work(sync: SyncScope) -> int:
        return int(sync.wallet.balance(telegram_id).amount)

    balance = await read_scope(container, work)
    subscriptions, _ = await scope.subscriptions.search(user_id=telegram_id, limit=1)
    orders = await scope.orders.count_for_user(telegram_id)
    suspended = customer.status is not UserStatus.ACTIVE

    body = A.CUSTOMER_CARD.format(
        name=customer.display_name,
        telegram_id=fa_digits(str(telegram_id)),
        username=f"@{customer.username}" if customer.username else "—",
        status="مسدود" if suspended else "فعال",
        balance=toman(balance),
        orders=fa_digits(str(orders)),
        subscriptions=fa_digits(str(len(subscriptions))),
    )
    ref = str(telegram_id)
    rows = [
        [
            K.btn(A.BTN_WALLET_ADD, AdminCB(action="wallet_add", ref=ref), style=K.YES),
            K.btn(A.BTN_WALLET_TAKE, AdminCB(action="wallet_take", ref=ref)),
        ],
        [
            K.btn(A.BTN_MESSAGE, AdminCB(action="message", ref=ref), style=K.GO),
            K.btn(A.BTN_SUBSCRIPTIONS, AdminCB(action="subs", ref=ref)),
        ],
        [
            K.btn(A.BTN_REINSTATE, AdminCB(action="reinstate", ref=ref), style=K.YES)
            if suspended
            else K.btn(A.BTN_SUSPEND, AdminCB(action="suspend", ref=ref), style=K.NO)
        ],
        [K.btn(A.BTN_BACK, AdminCB(action="menu"))],
    ]
    return body, K.stack(rows)


def _telegram_id_from(message: Message) -> int | None:
    """A forwarded message or a typed number.

    Forwarding cannot be mistyped, and a mistyped id here credits somebody
    else's wallet.
    """
    origin = getattr(message, "forward_from", None)
    if origin is not None:
        return int(origin.id)
    raw = normalize_input(message.text or "")
    return int(raw) if raw.isdigit() else None


# -- their wallet ----------------------------------------------------------


@router.callback_query(AdminCB.filter(F.action.in_({"wallet_add", "wallet_take"})))
async def on_wallet(
    query: CallbackQuery,
    callback_data: AdminCB,
    state: FSMContext,
    scope: Any = None,
    user: Any = None,
) -> None:
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return
    await state.update_data(
        target=callback_data.ref, sign=1 if callback_data.action == "wallet_add" else -1
    )
    await state.set_state(AdminFlow.wallet_amount)
    await safe_edit(query, A.WALLET_ASK_AMOUNT, markup=_back())


@router.message(AdminFlow.wallet_amount)
async def on_wallet_amount(message: Message, state: FSMContext) -> None:
    raw = normalize_input(message.text or "").replace(",", "")
    if not raw.isdigit() or int(raw) == 0:
        await answer(message, A.AMOUNT_NOT_A_NUMBER)
        return
    await state.update_data(amount=int(raw))
    await state.set_state(AdminFlow.wallet_reason)
    await answer(message, A.WALLET_ASK_REASON)


@router.message(AdminFlow.wallet_reason)
async def on_wallet_reason(
    message: Message,
    state: FSMContext,
    container: Container,
    scope: Any = None,
    user: Any = None,
) -> None:
    """The reason is required, not optional.

    Money appearing in a wallet with nothing recorded about why is a question
    nobody can answer six weeks later, and this is the path with the least
    ceremony around it - which is exactly why it needs the record.
    """
    if await _guard(scope, user) is None or user is None:
        await answer(message, A.NOT_AN_ADMIN)
        await state.clear()
        return

    data = await state.get_data()
    await state.clear()
    target = int(data.get("target") or 0)
    signed = int(data.get("amount") or 0) * int(data.get("sign") or 1)
    reason = normalize_input(message.text or "")
    actor = user.telegram_id

    def work(sync: SyncScope) -> int:
        sync.wallet.adjust(
            user_id=target, signed_amount=signed, actor_id=actor, reason_fa=reason
        )
        return int(sync.wallet.balance(target).amount)

    try:
        balance = await mutate_scope(container, work)
    except DomainError as failure:
        await answer(message, A.ACTION_FAILED.format(reason=str(failure)))
        return

    await answer(
        message, A.WALLET_DONE.format(balance=toman(balance)), reply_markup=K.main_menu()
    )


# -- writing to them -------------------------------------------------------


@router.callback_query(AdminCB.filter(F.action == "message"))
async def on_message_customer(
    query: CallbackQuery,
    callback_data: AdminCB,
    state: FSMContext,
    scope: Any = None,
    user: Any = None,
) -> None:
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return
    await state.update_data(target=callback_data.ref)
    await state.set_state(AdminFlow.messaging_customer)
    await safe_edit(query, A.MESSAGE_ASK_BODY, markup=_back())


@router.message(AdminFlow.messaging_customer)
async def on_message_body(
    message: Message,
    state: FSMContext,
    container: Container,
    scope: Any = None,
    user: Any = None,
) -> None:
    if await _guard(scope, user) is None:
        await answer(message, A.NOT_AN_ADMIN)
        await state.clear()
        return

    data = await state.get_data()
    await state.clear()
    target = int(data.get("target") or 0)
    body = message.text or ""

    rendered = RenderedMessage(
        key="admin.direct",
        # CRITICAL for the same reason the panel's direct message is: an
        # operator answering a named person is not marketing, and a reply a
        # preference can silence is a reply they believe they sent.
        category=NotificationCategory.CRITICAL,
        title_fa=A.MESSAGE_FROM_SUPPORT,
        body_fa=body,
    )

    def work(sync: SyncScope) -> None:
        sync.engine.dispatch(user_id=target, message=rendered, source="admin.direct")

    await mutate_scope(container, work)
    await answer(message, A.MESSAGE_SENT, reply_markup=K.main_menu())


# -- blocking them ---------------------------------------------------------


@router.callback_query(AdminCB.filter(F.action == "suspend"))
async def on_suspend(
    query: CallbackQuery,
    callback_data: AdminCB,
    state: FSMContext,
    scope: Any = None,
    user: Any = None,
) -> None:
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return
    await state.update_data(target=callback_data.ref)
    await state.set_state(AdminFlow.suspending_customer)
    await safe_edit(query, A.SUSPEND_ASK_REASON, markup=_back())


@router.message(AdminFlow.suspending_customer)
async def on_suspend_reason(
    message: Message, state: FSMContext, scope: Any = None, user: Any = None
) -> None:
    if await _guard(scope, user) is None:
        await answer(message, A.NOT_AN_ADMIN)
        await state.clear()
        return

    data = await state.get_data()
    await state.clear()
    customer = await scope.users.get_by_telegram_id(int(data.get("target") or 0))
    if customer is None:
        await answer(message, A.CUSTOMER_NOT_FOUND)
        return

    customer.suspend(reason=normalize_input(message.text or ""))
    await scope.users.update(customer)
    await answer(message, A.SUSPENDED, reply_markup=K.main_menu())


@router.callback_query(AdminCB.filter(F.action == "reinstate"))
async def on_reinstate(
    query: CallbackQuery, callback_data: AdminCB, scope: Any = None, user: Any = None
) -> None:
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return
    customer = await scope.users.get_by_telegram_id(int(callback_data.ref))
    if customer is None:
        await toast(query, A.CUSTOMER_NOT_FOUND, alert=True)
        return
    customer.reinstate()
    await scope.users.update(customer)
    await safe_edit(query, A.REINSTATED, markup=_back())


# -- their subscriptions ---------------------------------------------------
#
# Every action reaches the VPN panel before it changes our record, because
# `SubscriptionAdminService` is the same service the panel screen calls. A
# panel that refuses therefore leaves the subscription saying what it said
# before, and the operator is told which.


@router.callback_query(AdminCB.filter(F.action == "subs"))
async def on_subscriptions(
    query: CallbackQuery, callback_data: AdminCB, scope: Any = None, user: Any = None
) -> None:
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return

    subscriptions, _ = await scope.subscriptions.search(
        user_id=int(callback_data.ref), limit=QUEUE_LIMIT
    )
    if not subscriptions:
        await safe_edit(query, A.SUBSCRIPTIONS_EMPTY, markup=_back())
        return

    rows = [
        [
            K.btn(
                f"{subscription.plan_id[:8]} - {subscription.state.value}",
                AdminCB(action="sub", ref=subscription.id),
            )
        ]
        for subscription in subscriptions
    ]
    rows.append([K.btn(A.BTN_BACK, AdminCB(action="menu"))])
    await safe_edit(query, A.BTN_SUBSCRIPTIONS, markup=K.stack(rows))


@router.callback_query(AdminCB.filter(F.action == "sub"))
async def on_subscription(
    query: CallbackQuery, callback_data: AdminCB, scope: Any = None, user: Any = None
) -> None:
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return

    subscription = await scope.subscriptions.get(callback_data.ref)
    if subscription is None:
        await toast(query, A.SUBSCRIPTIONS_EMPTY, alert=True)
        return

    ref = subscription.id
    limit = subscription.traffic_limit_mib
    usage = (
        f"{fa_digits(str(round(subscription.traffic_used_mib / 1024)))} از "
        f"{fa_digits(str(round(limit / 1024)))} گیگابایت"
        if limit
        else "نامحدود"
    )
    body = A.SUBSCRIPTION_CARD.format(
        plan=subscription.plan_id[:8],
        state=subscription.state.value,
        expires=fa_digits(subscription.expires_at.strftime("%Y-%m-%d")),
        usage=usage,
        node=subscription.node_id or "—",
    )

    revoked = subscription.state is SubscriptionState.REVOKED
    suspended = subscription.state is SubscriptionState.SUSPENDED
    rows = []
    if not revoked:
        rows.append(
            [
                K.btn(A.BTN_SUB_EXTEND, AdminCB(action="sub_extend", ref=ref), style=K.YES),
                K.btn(A.BTN_SUB_TRAFFIC, AdminCB(action="sub_traffic", ref=ref), style=K.YES),
            ]
        )
        rows.append(
            [
                K.btn(A.BTN_SUB_RESUME, AdminCB(action="sub_resume", ref=ref), style=K.GO)
                if suspended
                else K.btn(A.BTN_SUB_SUSPEND, AdminCB(action="sub_suspend", ref=ref)),
                K.btn(A.BTN_SUB_REVOKE, AdminCB(action="sub_revoke", ref=ref), style=K.NO),
            ]
        )
    rows.append([K.btn(A.BTN_BACK, AdminCB(action="menu"))])
    await safe_edit(query, body, markup=K.stack(rows))


@router.callback_query(AdminCB.filter(F.action == "sub_resume"))
async def on_sub_resume(
    query: CallbackQuery, callback_data: AdminCB, scope: Any = None, user: Any = None
) -> None:
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return
    try:
        await scope.subscription_admin.resume(callback_data.ref)
    except (DomainError, PanelError) as failure:
        await toast(query, A.SUB_PANEL_REFUSED.format(reason=str(failure)), alert=True)
        return
    await safe_edit(query, A.SUB_DONE, markup=_back())


@router.callback_query(
    AdminCB.filter(F.action.in_({"sub_extend", "sub_traffic", "sub_suspend", "sub_revoke"}))
)
async def on_sub_action(
    query: CallbackQuery,
    callback_data: AdminCB,
    state: FSMContext,
    scope: Any = None,
    user: Any = None,
) -> None:
    """The three that need a number or a reason before they can run."""
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return

    await state.update_data(subscription=callback_data.ref, sub_action=callback_data.action)
    if callback_data.action == "sub_extend":
        await state.set_state(AdminFlow.subscription_days)
        await safe_edit(query, A.SUB_ASK_DAYS, markup=_back())
    elif callback_data.action == "sub_traffic":
        await state.set_state(AdminFlow.subscription_gib)
        await safe_edit(query, A.SUB_ASK_GIB, markup=_back())
    else:
        await state.set_state(AdminFlow.subscription_reason)
        await safe_edit(query, A.SUB_ASK_REASON, markup=_back())


@router.message(AdminFlow.subscription_days)
@router.message(AdminFlow.subscription_gib)
async def on_sub_number(
    message: Message, state: FSMContext, scope: Any = None, user: Any = None
) -> None:
    if await _guard(scope, user) is None:
        await answer(message, A.NOT_AN_ADMIN)
        await state.clear()
        return

    raw = normalize_input(message.text or "")
    if not raw.isdigit() or int(raw) == 0:
        await answer(message, A.AMOUNT_NOT_A_NUMBER)
        return

    data = await state.get_data()
    await state.clear()
    subscription_id = str(data.get("subscription") or "")
    amount = int(raw)

    try:
        if data.get("sub_action") == "sub_extend":
            await scope.subscription_admin.extend(subscription_id, days=amount)
        else:
            await scope.subscription_admin.add_traffic(subscription_id, gib=amount)
    except (DomainError, PanelError) as failure:
        await answer(message, A.SUB_PANEL_REFUSED.format(reason=str(failure)))
        return

    await answer(message, A.SUB_DONE, reply_markup=K.main_menu())


@router.message(AdminFlow.subscription_reason)
async def on_sub_reason(
    message: Message, state: FSMContext, scope: Any = None, user: Any = None
) -> None:
    if await _guard(scope, user) is None:
        await answer(message, A.NOT_AN_ADMIN)
        await state.clear()
        return

    data = await state.get_data()
    await state.clear()
    subscription_id = str(data.get("subscription") or "")
    reason = normalize_input(message.text or "")

    try:
        if data.get("sub_action") == "sub_suspend":
            await scope.subscription_admin.suspend(subscription_id, reason_fa=reason)
        else:
            await scope.subscription_admin.revoke(subscription_id, reason_fa=reason)
    except (DomainError, PanelError) as failure:
        await answer(message, A.SUB_PANEL_REFUSED.format(reason=str(failure)))
        return

    await answer(message, A.SUB_DONE, reply_markup=K.main_menu())


# -- orders ----------------------------------------------------------------


@router.callback_query(AdminCB.filter(F.action == "orders"))
async def on_orders(query: CallbackQuery, scope: Any = None, user: Any = None) -> None:
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return

    orders, _ = await scope.orders.search(limit=QUEUE_LIMIT)
    if not orders:
        await safe_edit(query, A.ORDERS_EMPTY, markup=_back())
        return

    rows = [
        [K.btn(f"{order.number} - {order.state.value}", AdminCB(action="order", ref=order.id))]
        for order in orders
    ]
    rows.append([K.btn(A.BTN_BACK, AdminCB(action="menu"))])
    await safe_edit(query, A.ORDERS_TITLE, markup=K.stack(rows))


@router.callback_query(AdminCB.filter(F.action == "order"))
async def on_order(
    query: CallbackQuery, callback_data: AdminCB, scope: Any = None, user: Any = None
) -> None:
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return

    order = await scope.orders.get(callback_data.ref)
    if order is None:
        await toast(query, A.ORDERS_EMPTY, alert=True)
        return

    body = A.ORDER_CARD.format(
        number=order.number,
        plan=order.plan_name_fa,
        total=toman(order.total.amount),
        state=order.state.value,
        user_id=fa_digits(str(order.user_id)),
        placed=fa_digits(order.placed_at.strftime("%Y-%m-%d %H:%M")),
    )
    rows = []
    # Only where a retry is the actual remedy. Offering it on a delivered order
    # invites a second account nobody is billing for.
    if order.state in {OrderState.PAID, OrderState.FAILED}:
        rows.append(
            [K.btn(A.BTN_RETRY_PROVISION, AdminCB(action="retry", ref=order.id), style=K.GO)]
        )
    rows.append([K.btn(A.BTN_BACK, AdminCB(action="orders"))])
    await safe_edit(query, body, markup=K.stack(rows))


@router.callback_query(AdminCB.filter(F.action == "retry"))
async def on_retry(
    query: CallbackQuery, callback_data: AdminCB, scope: Any = None, user: Any = None
) -> None:
    """A refusing panel is an answer, not a fault.

    The operator asked "what happens if I try again", and "the panel is still
    saying no" answers it - so it is reported rather than raised.
    """
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return
    try:
        await scope.provisioning.provision(callback_data.ref)
    except (DomainError, PanelError) as failure:
        await safe_edit(query, A.RETRY_FAILED.format(reason=str(failure)), markup=_back("orders"))
        return
    await safe_edit(query, A.RETRY_OK, markup=_back("orders"))


# -- the numbers -----------------------------------------------------------


@router.callback_query(AdminCB.filter(F.action == "stats"))
async def on_stats(
    query: CallbackQuery, container: Container, scope: Any = None, user: Any = None
) -> None:
    """The dashboard's own metric cards, rendered as lines.

    The same builder the panel's dashboard uses, so the two cannot disagree
    about what "today" means or which orders count.
    """
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return

    def work(services: dict[str, Any]) -> list[tuple[str, str]]:
        dashboard = services["dashboard"].build()
        return [(card.label_fa, card.display) for card in dashboard.metrics]

    try:
        # The panel's own dashboard builder, on its own reporting session, so
        # the two cannot disagree about what "today" means or which orders
        # count towards it.
        metrics = await run_report(container, work)
    except Exception as failure:
        await toast(query, A.ACTION_FAILED.format(reason=str(failure)), alert=True)
        return

    lines = "\n".join(A.STATS_ROW.format(label=label, value=value) for label, value in metrics)
    await safe_edit(
        query, A.STATS_CARD.format(title=A.BTN_STATS, lines=lines), markup=_back()
    )


# -- shared ----------------------------------------------------------------


def _back(to: str = "menu") -> InlineKeyboardMarkup:
    return K.single(K.btn(A.BTN_BACK, AdminCB(action=to)))
