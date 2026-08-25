"""Support tickets.

Deliberate funnel: the support screen leads with the FAQ, because most
incoming tickets are "how do I install it" and answering those instantly is
better for the customer than a 30-minute queue. Opening a ticket is always
one tap away, never hidden.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from geekvpn.application.bot.read_models import TicketState as CardTicketState
from geekvpn.application.bot.services import BotServices
from geekvpn.presentation.bot.handlers.common import answer, safe_edit, toast
from geekvpn.presentation.bot.states import Support
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import render as R
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB, TicketCB
from geekvpn.presentation.bot.ui.fa import normalize_input

logger = structlog.stdlib.get_logger(__name__)

router = Router(name="support")

MIN_MESSAGE = 10

TOPICS: tuple[tuple[str, str], ...] = (
    ("connection", T.TOPIC_CONNECTION),
    ("payment", T.TOPIC_PAYMENT),
    ("account", T.TOPIC_ACCOUNT),
    ("speed", T.TOPIC_SPEED),
    ("other", T.TOPIC_OTHER),
)
TOPIC_LABELS = dict(TOPICS)


def _menu_keyboard() -> InlineKeyboardMarkup:
    return K.stack(
        [
            [K.btn(f"\u2753 {T.MENU_FAQ}", NavCB(to="faq"))],
            [K.btn(T.BTN_NEW_TICKET, TicketCB(action="new", ref="-"))],
            [K.btn(T.BTN_MY_TICKETS, TicketCB(action="list", ref="-"))],
            [K.home_button()],
        ]
    )


def _topic_keyboard() -> InlineKeyboardMarkup:
    rows = [[K.btn(label, TicketCB(action="topic", ref=key))] for key, label in TOPICS]
    rows.append([K.btn(T.BTN_CANCEL, NavCB(to="support"))])
    return K.stack(rows)


@router.message(Command("support"))
async def on_support_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await answer(message, f"{T.SUPPORT_TITLE}\n\n{T.SUPPORT_INTRO}", reply_markup=_menu_keyboard())


@router.callback_query(NavCB.filter(F.to == "support"))
async def on_support(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await toast(query)
    await safe_edit(query, f"{T.SUPPORT_TITLE}\n\n{T.SUPPORT_INTRO}", markup=_menu_keyboard())


@router.callback_query(TicketCB.filter(F.action == "new"))
async def on_new_ticket(query: CallbackQuery, state: FSMContext) -> None:
    await toast(query)
    await state.set_state(Support.choosing_topic)
    await safe_edit(query, T.TICKET_CHOOSE_TOPIC, markup=_topic_keyboard())


@router.callback_query(Support.choosing_topic, TicketCB.filter(F.action == "topic"))
async def on_topic(query: CallbackQuery, callback_data: TicketCB, state: FSMContext) -> None:
    await toast(query)
    await state.update_data(topic=callback_data.ref)
    await state.set_state(Support.writing_message)
    label = TOPIC_LABELS.get(callback_data.ref, T.TOPIC_OTHER)
    await safe_edit(
        query,
        f"{label}\n\n{T.TICKET_ASK_MESSAGE}",
        markup=K.single(K.btn(T.BTN_CANCEL, NavCB(to="support"))),
    )


@router.message(Support.writing_message, F.text)
async def on_ticket_message(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    body = normalize_input(message.text or "")
    if len(body) < MIN_MESSAGE:
        await answer(message, T.TICKET_TOO_SHORT)
        return
    if user is None:
        await answer(message, T.ERR_GENERIC)
        return

    data = await state.get_data()
    topic = str(data.get("topic") or "other")

    try:
        ticket = await services.tickets.open_ticket(user.id, topic=topic, message=body)
    except Exception:
        # Logged, not merely apologised for. This `except` swallowed the
        # exception whole - no traceback, nothing in the log at all - so a
        # customer who could not open a ticket left no evidence of why, and
        # every attempt to diagnose it from the outside came back empty. The
        # same mistake, in the same shape, as the one already fixed in
        # `purchase.py`.
        logger.exception("bot.ticket_open_failed", topic=topic)
        await answer(message, T.ERR_GENERIC)
        return

    await state.clear()
    await answer(
        message,
        T.TICKET_CREATED.format(
            ref=f"<code>{ticket.reference}</code>",
            sla="\u06f3\u06f0 \u062f\u0642\u06cc\u0642\u0647",
        ),
        reply_markup=K.main_menu(),
    )


@router.message(Support.writing_message, F.photo)
async def on_ticket_photo(message: Message) -> None:
    """Screenshots are welcome but must carry a caption.

    An image with no words gives an agent nothing to work with, so we ask for
    the description rather than opening an empty ticket.
    """
    if message.caption:
        return
    await answer(message, T.TICKET_ASK_MESSAGE)


@router.callback_query(TicketCB.filter(F.action == "list"))
async def on_ticket_list(query: CallbackQuery, services: BotServices, user: Any = None) -> None:
    await toast(query)
    if user is None:
        return
    try:
        tickets = await services.tickets.list_for_user(user.id)
    except Exception:
        # An empty list and a failed read look identical to the customer, so
        # the difference has to survive somewhere.
        logger.exception("bot.ticket_list_failed")
        tickets = []
    rows = [
        [K.btn(f"{ticket.topic_fa} - {ticket.reference}", TicketCB(action="view", ref=ticket.reference))]
        for ticket in tickets
    ]
    rows.append([K.btn(T.BTN_BACK, NavCB(to="support"))])
    await safe_edit(query, R.ticket_list(tickets), markup=K.stack(rows))


@router.callback_query(TicketCB.filter(F.action == "view"))
async def on_ticket_view(
    query: CallbackQuery, callback_data: TicketCB, services: BotServices, user: Any = None
) -> None:
    """One ticket and its conversation.

    Addressed by reference rather than id: the reference is short enough for a
    callback payload, it is what the customer is shown everywhere else, and it
    is resolved against their own tickets - so a crafted one finds nothing.
    """
    await toast(query)
    if user is None:
        return

    card = await services.tickets.find_by_reference(user.id, reference=callback_data.ref)
    if card is None:
        await safe_edit(query, T.TICKET_REPLY_UNKNOWN, markup=_back_to_list())
        return

    messages = await services.tickets.thread(user.id, ticket_id=str(card.ticket_id))
    buttons = []
    if card.state is not CardTicketState.CLOSED:
        buttons.append([K.btn(T.BTN_TICKET_REPLY, TicketCB(action="reply", ref=card.reference))])
    buttons.append([K.btn(T.BTN_BACK, TicketCB(action="list", ref="-"))])

    await safe_edit(query, R.ticket_thread(card, messages), markup=K.stack(buttons))


@router.callback_query(TicketCB.filter(F.action == "reply"))
async def on_ticket_reply(
    query: CallbackQuery, callback_data: TicketCB, state: FSMContext
) -> None:
    await toast(query)
    await state.update_data(reply_reference=callback_data.ref)
    await state.set_state(Support.replying)
    await safe_edit(query, T.TICKET_ASK_REPLY, markup=_back_to_list())


#: A ticket reference as it is printed in every message the bot sends about
#: one. Read back out of a quoted message, which is what makes "reply to this"
#: work without storing a message id anywhere.
REFERENCE = re.compile(r"\bSUP-\d{4}-\d{6}\b", re.IGNORECASE)


@router.message(F.reply_to_message, F.text)
async def on_reply_to_support(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    """Answer a ticket by replying to the message that carried the answer.

    The ticket is identified from the text being replied to, not from a stored
    message id. Telegram hands us the quoted message in full, the reference is
    already printed in it, and it is resolved against this customer's own
    tickets - so nothing has to be remembered between two processes, and a
    forged quote resolves to nothing.

    Registered before the FSM handlers below on purpose: someone mid-flow who
    replies to an older support message means the reply, not the flow.
    """
    quoted = message.reply_to_message
    found = REFERENCE.search((quoted.text or quoted.caption or "") if quoted else "")
    if found is None:
        # Not about a ticket. Fall through to whatever else was expecting this
        # message rather than swallowing it.
        await _fall_through(message, state, services, user)
        return

    await state.clear()
    await _post_reply(
        message,
        services,
        user,
        reference=found.group(0),
        body=normalize_input(message.text or ""),
    )


async def _fall_through(
    message: Message, state: FSMContext, services: BotServices, user: Any
) -> None:
    """A reply that is not about a ticket still belongs to whoever wanted it.

    Only the two flows that read free text can be here; anything else gets the
    same nudge the catch-all would have given.
    """
    current = await state.get_state()
    if current == Support.writing_message.state:
        await on_ticket_message(message, state, services, user)
        return
    if current == Support.replying.state:
        await on_ticket_reply_text(message, state, services, user)
        return
    await answer(message, T.ERR_UNKNOWN_COMMAND, reply_markup=K.main_menu())


@router.message(Support.replying, F.text)
async def on_ticket_reply_text(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    data = await state.get_data()
    await state.clear()
    await _post_reply(
        message,
        services,
        user,
        reference=str(data.get("reply_reference") or ""),
        body=normalize_input(message.text or ""),
    )


async def _post_reply(
    message: Message, services: BotServices, user: Any, *, reference: str, body: str
) -> None:
    """Append one customer reply, from whichever route asked for it."""
    if user is None or not reference:
        await answer(message, T.TICKET_REPLY_UNKNOWN, reply_markup=K.main_menu())
        return
    if len(body) < MIN_MESSAGE:
        await answer(message, T.TICKET_TOO_SHORT)
        return

    card = await services.tickets.find_by_reference(user.id, reference=reference)
    if card is None:
        await answer(message, T.TICKET_REPLY_UNKNOWN, reply_markup=K.main_menu())
        return
    if card.state is CardTicketState.CLOSED:
        await answer(message, T.TICKET_CLOSED_CANNOT_REPLY, reply_markup=K.main_menu())
        return

    try:
        await services.tickets.reply(user.id, ticket_id=str(card.ticket_id), message=body)
    except Exception:
        logger.exception("bot.ticket_reply_failed", reference=reference)
        await answer(message, T.ERR_GENERIC)
        return

    await answer(message, T.TICKET_REPLY_SENT, reply_markup=K.main_menu())


def _back_to_list() -> Any:
    return K.single(K.btn(T.BTN_BACK, TicketCB(action="list", ref="-")))
