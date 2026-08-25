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
from aiogram.enums import ButtonStyle
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from geekvpn.application.payments.review_service import ApprovalRequest
from geekvpn.application.support.ticket_service import ReplyRequest
from geekvpn.domain.base.errors import DomainError
from geekvpn.domain.identity.admin import Admin
from geekvpn.domain.identity.permissions import AdminRole
from geekvpn.domain.payments.enums import PaymentState
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.di.sync_scope import SyncScope
from geekvpn.presentation.api.admin_common import mutate_scope, read_scope
from geekvpn.presentation.bot.handlers.common import answer, safe_edit, toast
from geekvpn.presentation.bot.ui import admin_text as A
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui.callbacks import AdminCB
from geekvpn.presentation.bot.ui.fa import fa_digits, toman

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


# -- access ----------------------------------------------------------------


async def current_admin(scope: Any, user: Any) -> Admin | None:
    """The admin record behind this Telegram account, if there is one."""
    if user is None or scope is None:
        return None
    found: Admin | None = await scope.admins.get_by_telegram_id(user.telegram_id)
    return found


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
            [K.btn(A.BTN_PAYMENTS, AdminCB(action="payments"))],
            [K.btn(A.BTN_TICKETS, AdminCB(action="tickets"))],
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
                K.btn(
                    A.BTN_APPROVE,
                    AdminCB(action="approve", ref=payment_id),
                    style=ButtonStyle.SUCCESS,
                ),
                K.btn(
                    A.BTN_REJECT,
                    AdminCB(action="reject", ref=payment_id),
                    style=ButtonStyle.DANGER,
                ),
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
                    K.btn(
                        A.BTN_REPLY,
                        AdminCB(action="reply", ref=ticket_id),
                        style=ButtonStyle.PRIMARY,
                    ),
                    K.btn(
                        A.BTN_CLOSE_TICKET,
                        AdminCB(action="close", ref=ticket_id),
                        style=ButtonStyle.DANGER,
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


# -- shared ----------------------------------------------------------------


def _back(to: str = "menu") -> InlineKeyboardMarkup:
    return K.single(K.btn(A.BTN_BACK, AdminCB(action=to)))
