"""Typed callback data.

Aiogram's `CallbackData` factory is used everywhere instead of hand-rolled
`f"buy:{plan_id}"` strings. Three reasons, all of which have bitten real bots:

1. **The 64-byte limit is a hard Telegram constraint.** A raw UUID is 36
   characters, so `purchase:confirm:<uuid>:<uuid>` silently exceeds it and
   Telegram rejects the *whole keyboard*. We store short tokens and keep the
   heavy state in FSM instead.
2. **Parsing is centralised.** A malformed callback becomes a filter miss, not
   an `IndexError` inside a handler.
3. **Prefixes are namespaced**, so two features cannot collide.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class NavCB(CallbackData, prefix="nav"):
    """Top-level navigation between menus."""

    to: str


class ShopCB(CallbackData, prefix="shop"):
    """Storefront browsing.

    `ref` is a short token (first 8 hex chars of the entity id) resolved
    against the FSM-cached storefront, never a full UUID -- see the 64-byte
    note above.
    """

    action: str  # category | product | plan | back
    ref: str = ""


class BuyCB(CallbackData, prefix="buy"):
    action: str  # start | coupon | drop_coupon | pay | confirm | cancel
    ref: str = ""


class PayCB(CallbackData, prefix="pay"):
    action: str  # method | receipt | cancel | check
    method: str = ""  # wallet | card | crypto
    ref: str = ""


class SubCB(CallbackData, prefix="sub"):
    """An owned subscription."""

    action: str  # view | config | qr | renew | traffic | rotate
    ref: str = ""


class WalletCB(CallbackData, prefix="wlt"):
    action: str  # topup | history | page | method
    ref: str = ""


class RefCB(CallbackData, prefix="ref"):
    action: str  # link | stats | payouts | share


class TicketCB(CallbackData, prefix="tkt"):
    action: str  # new | view | reply | close | topic | list
    ref: str = ""


class ProfileCB(CallbackData, prefix="prf"):
    action: str  # view | edit_name | edit_phone | edit_email | delete


class SettingsCB(CallbackData, prefix="set"):
    """`toggle` flips a boolean preference; `key` names it."""

    action: str  # view | toggle | choose
    key: str = ""
    value: str = ""


class FaqCB(CallbackData, prefix="faq"):
    action: str  # topic | item | back
    ref: str = ""


class StatusCB(CallbackData, prefix="sts"):
    action: str  # refresh | detail
    ref: str = ""


class PageCB(CallbackData, prefix="pg"):
    """Generic pagination. `scope` says which list is being paged."""

    scope: str
    page: int


class NoopCB(CallbackData, prefix="noop"):
    """A button that exists only as a label (page counters, headers).

    Telegram requires every inline button to carry callback data; answering
    the query with no side effect stops the client's loading spinner.
    """

    tag: str = ""
