"""FSM state groups.

State lives in Redis (see `factory.create_dispatcher`), so a bot restart or a
second replica does not drop a user halfway through typing a coupon code.

Convention: every group has an explicit terminal path. A user must always be
able to reach the main menu, so every flow's keyboard carries a cancel button
and `/start` clears state unconditionally.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    """First-contact onboarding.

    Deliberately short: Telegram already gave us an authenticated identity, so
    asking for a name and a phone number again would be theatre. We only ask
    for what we cannot infer, and every step is skippable.
    """

    language = State()
    display_name = State()
    contact = State()


class Purchase(StatesGroup):
    browsing = State()
    reviewing = State()
    entering_coupon = State()
    choosing_payment = State()
    awaiting_receipt = State()
    awaiting_crypto_txid = State()


class Renewal(StatesGroup):
    choosing_plan = State()
    reviewing = State()


class Wallet(StatesGroup):
    idle = State()
    entering_amount = State()
    choosing_method = State()
    awaiting_receipt = State()
    awaiting_crypto_txid = State()


class Support(StatesGroup):
    choosing_topic = State()
    writing_subject = State()
    writing_message = State()
    in_thread = State()
    #: Writing a reply to a ticket that already exists.
    replying = State()


class Profile(StatesGroup):
    editing_name = State()
    editing_phone = State()
    editing_email = State()
    confirming_delete = State()
