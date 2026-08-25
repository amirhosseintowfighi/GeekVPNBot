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


def url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=_label(text), url=url)


def noop_btn(text: str, *, tag: str = "") -> InlineKeyboardButton:
    return btn(text, NoopCB(tag=tag))


def back_button(to: str = "home") -> InlineKeyboardButton:
    return btn(T.BTN_BACK, NavCB(to=to))


def home_button() -> InlineKeyboardButton:
    return btn(T.BTN_HOME, NavCB(to="home"))


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
    # Colour is a signal, not decoration. Buying and topping up are the two
    # things a customer came here to do, so those are the coloured ones; making
    # all nine primary would say nothing at all. Requires Bot API 9.4 - older
    # clients render the same buttons uncoloured rather than failing.
    builder.row(
        KeyboardButton(text=TAP_SHOP, style=ButtonStyle.PRIMARY),
        KeyboardButton(text=TAP_DASHBOARD),
    )
    builder.row(
        KeyboardButton(text=TAP_WALLET, style=ButtonStyle.SUCCESS),
        KeyboardButton(text=TAP_REFERRAL),
    )
    builder.row(KeyboardButton(text=TAP_SUPPORT), KeyboardButton(text=TAP_STATUS))
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
    builder.row(btn(confirm_text or T.BTN_CONFIRM, confirm_cb))
    builder.row(btn(cancel_text or T.BTN_CANCEL, cancel_cb))
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
