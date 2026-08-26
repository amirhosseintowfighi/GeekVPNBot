"""Keyboard construction.

RTL note that is easy to miss: Telegram lays inline keyboard buttons out
**left to right regardless of the UI language**. It is not a text run, so the
bidi algorithm does not apply and there is no way to mirror it.

So we do not fight it -- we design for it. The convention throughout the bot,
chosen once and applied everywhere:

- The **primary/forward** action is the *first* button in its row.
- Back/cancel lives on its own final row, never beside a destructive action.

That gives a consistent, learnable geometry instead of a keyboard that looks
mirrored on some screens and not others.

Width: three columns is the practical maximum before Persian labels get
ellipsised on a narrow phone. Most menus use two.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Final

from aiogram.enums import ButtonStyle
from aiogram.types import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from geekvpn.presentation.bot.ui import emoji as E
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import (
    NavCB,
    NoopCB,
    PageCB,
)
from geekvpn.presentation.bot.ui.fa import fa_digits, truncate

# Telegram truncates inline button labels around this width on a narrow
# device. Enforced here so a long Persian product name degrades gracefully
# rather than becoming unreadable.
MAX_LABEL = 32


#: What the three colours mean here. Bot API 9.4 offers exactly these, and the
#: value of a colour is entirely in its consistency - a green that sometimes
#: means "confirm" and sometimes means "back" is worse than no colour at all.
#:
#: PRIMARY  a choice among options, or a way further in: a payment method, a
#:          category, the main menu.
#: SUCCESS  the thing this screen exists for: pay, confirm, top up, renew,
#:          copy the card number, share the link.
#: DANGER   leaving without doing it: cancel, back, close - and anything that
#:          ends something: reject, revoke, delete.
#:
#: The earlier rule here was that most buttons stay plain, on the reasoning
#: that a screen of uniform colour recommends nothing. That is true of a screen
#: where every button is the *same* colour, and it was read as an argument for
#: colouring almost nothing - most screens ended up a wall of grey with one
#: blue button, which is not obviously better at pointing anywhere.
#:
#: Three colours used consistently do point: the reader learns that red always
#: means "this takes me back out" and green always means "this is the button",
#: and stops reading labels on the buttons they were not going to press.
GO = ButtonStyle.PRIMARY
YES = ButtonStyle.SUCCESS
NO = ButtonStyle.DANGER


def _label(value: str) -> str:
    return truncate(value, MAX_LABEL)


def btn(text: str, callback: Any, *, style: str | None = None) -> InlineKeyboardButton:
    """One inline button.

    `style` is Bot API 9.4's button colour - primary, success or danger. It is
    passed through rather than decided here: which action is destructive is
    something only the screen showing it knows.

    Accepts a `CallbackData` instance or a raw string.
    """
    data = callback if isinstance(callback, str) else callback.pack()
    return InlineKeyboardButton(text=_label(text), callback_data=data, style=style)


def copy_btn(text: str, value: str, *, style: str | None = None) -> InlineKeyboardButton:
    """A button that puts `value` on the customer's clipboard.

    Telegram copies it client-side - no callback, no round trip, no chance of
    the bot being slow at the moment somebody is holding their banking app
    open. It exists because the alternative is asking a customer to long-press
    a `<code>` block and drag two handles over a sixteen-digit number, and the
    digits they mistype are the ones that make a transfer unmatchable.
    """
    return InlineKeyboardButton(text=_label(text), copy_text=CopyTextButton(text=value), style=style)


def url_btn(text: str, url: str, *, style: str | None = None) -> InlineKeyboardButton:
    """A link button, colourable like any other.

    It takes `style` because a link is often the primary action on its screen -
    sharing a referral link, opening the Mini App - and a plain button beside a
    coloured secondary one points the customer at the wrong thing.
    """
    return InlineKeyboardButton(text=_label(text), url=url, style=style)


def noop_btn(text: str, *, tag: str = "") -> InlineKeyboardButton:
    return btn(text, NoopCB(tag=tag))


def back_button(to: str = "home") -> InlineKeyboardButton:
    """Red, because it leaves this screen without doing what it was for."""
    return btn(T.BTN_BACK, NavCB(to=to), style=NO)


def home_button() -> InlineKeyboardButton:
    """Blue: not an escape but a destination, and the one every screen offers."""
    return btn(T.BTN_HOME, NavCB(to="home"), style=GO)


#: What the persistent keyboard's buttons actually say.
#:
#: A tap sends this exact string. The handlers used to compare against the bare
#: label in `text.py` - "تنظیمات" - while the button sent "⚙️ تنظیمات", so every
#: one of them fell through to "I did not understand that". Only the shop
#: button worked, because one handler somewhere used `contains` instead.
#:
#: Defined once, and matched against the same constant, so the caption and the
#: handler cannot describe different strings.
TAP_SHOP: Final = f"{E.SHOP} {T.MENU_SHOP}"
TAP_DASHBOARD: Final = f"{E.DASHBOARD} {T.MENU_DASHBOARD}"
TAP_WALLET: Final = f"{E.WALLET} {T.MENU_WALLET}"
TAP_REFERRAL: Final = f"{E.REFERRAL} {T.MENU_REFERRAL}"
TAP_SUPPORT: Final = f"{E.SUPPORT} {T.MENU_SUPPORT}"
TAP_STATUS: Final = f"{E.STATUS} {T.MENU_STATUS}"
TAP_PROFILE: Final = f"{E.PROFILE} {T.MENU_PROFILE}"
TAP_FAQ: Final = f"{E.FAQ} {T.MENU_FAQ}"
TAP_SETTINGS: Final = f"{E.SETTINGS} {T.MENU_SETTINGS}"


def main_menu() -> ReplyKeyboardMarkup:
    """The persistent reply keyboard.

    A reply keyboard rather than an inline one because it survives scrolling
    and is always one tap away -- which matters for a bot that is someone's
    only interface to a service they paid for.

    Ordering within each row puts the more-used action first (leftmost),
    matching the inline convention above.
    """
    builder = ReplyKeyboardBuilder()
    # Coloured top to bottom in descending order of what a customer came for.
    # Only two were coloured before, on the reasoning that colouring all nine
    # says nothing - but nine buttons in one uniform grey say nothing either,
    # and this keyboard is on screen permanently, under every message.
    #
    # The bottom row stays plain on purpose: profile, help and settings are
    # where a customer goes when something is already wrong, and they are the
    # one part of this keyboard that should not compete.
    #
    # Requires Bot API 9.4 - older clients render the same buttons uncoloured
    # rather than failing.
    builder.row(
        KeyboardButton(text=TAP_SHOP, style=ButtonStyle.PRIMARY),
        KeyboardButton(text=TAP_DASHBOARD, style=ButtonStyle.PRIMARY),
    )
    builder.row(
        KeyboardButton(text=TAP_WALLET, style=ButtonStyle.SUCCESS),
        KeyboardButton(text=TAP_REFERRAL, style=ButtonStyle.SUCCESS),
    )
    builder.row(
        KeyboardButton(text=TAP_SUPPORT, style=ButtonStyle.PRIMARY),
        KeyboardButton(text=TAP_STATUS),
    )
    builder.row(
        KeyboardButton(text=TAP_PROFILE),
        KeyboardButton(text=TAP_FAQ),
        KeyboardButton(text=TAP_SETTINGS),
    )
    return builder.as_markup(
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=T.PLACEHOLDER,
    )


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def confirm_cancel(
    confirm_cb: Any, cancel_cb: Any, *, confirm_text: str = "", cancel_text: str = ""
) -> InlineKeyboardMarkup:
    """Confirm first, cancel on its own row.

    Never side by side: a mis-tap on a payment confirmation is expensive, and
    a 50/50 row is exactly how that happens.
    """
    builder = InlineKeyboardBuilder()
    builder.row(btn(confirm_text or T.BTN_CONFIRM, confirm_cb, style=YES))
    builder.row(btn(cancel_text or T.BTN_CANCEL, cancel_cb, style=NO))
    return builder.as_markup()


def single(button: InlineKeyboardButton) -> InlineKeyboardMarkup:
    """One button on its own row. Callers pass a built button, so the same
    helpers that build rows elsewhere (`btn`, `home_button`) work here too."""
    builder = InlineKeyboardBuilder()
    builder.row(button)
    return builder.as_markup()


def back_only(to: str = "home") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(back_button(to))
    return builder.as_markup()


def stack(
    rows: Iterable[Sequence[InlineKeyboardButton]],
    *,
    back_to: str | None = None,
    home: bool = False,
) -> InlineKeyboardMarkup:
    """Assemble explicit rows, then append a standard navigation row."""
    builder = InlineKeyboardBuilder()
    for row in rows:
        cells = [c for c in row if c is not None]
        if cells:
            builder.row(*cells)
    nav: list[InlineKeyboardButton] = []
    if back_to is not None:
        nav.append(back_button(back_to))
    if home:
        nav.append(home_button())
    if nav:
        builder.row(*nav)
    return builder.as_markup()


def grid(
    buttons: Sequence[InlineKeyboardButton],
    *,
    width: int = 2,
    back_to: str | None = None,
    home: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for button in buttons:
        builder.add(button)
    builder.adjust(width)
    nav: list[InlineKeyboardButton] = []
    if back_to is not None:
        nav.append(back_button(back_to))
    if home:
        nav.append(home_button())
    if nav:
        builder.row(*nav)
    return builder.as_markup()


def pagination_row(*, scope: str, page: int, total_pages: int) -> list[InlineKeyboardButton]:
    """A prev/counter/next row.

    The arrow glyphs are intentionally swapped relative to a Latin UI: in an
    RTL mental model "next" advances leftward. `E.NEXT` is therefore a
    left-pointing triangle. Buttons still lay out LTR, so "next" sits first,
    matching the primary-action-first rule.
    """
    if total_pages <= 1:
        return []
    row: list[InlineKeyboardButton] = []
    if page < total_pages - 1:
        row.append(btn(E.NEXT, PageCB(scope=scope, page=page + 1)))
    row.append(noop_btn(f"{fa_digits(page + 1)} / {fa_digits(total_pages)}", tag=scope))
    if page > 0:
        row.append(btn(E.PREV, PageCB(scope=scope, page=page - 1)))
    return row


def toggle_label(text: str, enabled: bool) -> str:
    """`✅ فعال` / `⬜ غیرفعال` prefix for a settings row."""
    mark = "\u2705" if enabled else "\u2b1c"
    state = T.ON if enabled else T.OFF
    return f"{mark} {text} \u2014 {state}"
