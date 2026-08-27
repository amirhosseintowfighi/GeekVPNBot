"""Screens a reseller may rewrite, and how one is resolved.

Not every string in the bot. A curated list, and the curation is the design:

* Rewriting all of them would mean routing several hundred `T.X` references
  through a lookup, which is a large change to every handler for a feature
  almost nobody uses past the first three screens.
* Most of the rest are labels, errors and toasts - "cancel", "something went
  wrong", "copied" - where a reseller's own wording adds nothing and a bad
  edit breaks a button.

What is here is what a customer actually reads and forms an impression from:
the greeting, the shop, support, and the reasons to trust the seller. Those are
the screens where a reseller's voice is the point.

An override is stored only when it differs from ours. A shop that has not
touched a screen follows the platform's copy, so improving a message improves
it everywhere it has not been deliberately taken over - the opposite of seeding
each reseller with a frozen snapshot of this file.
"""

from __future__ import annotations

from typing import Any, Final

from geekvpn.presentation.bot.ui import text as T

#: What a reseller may rewrite, and what to call each one on their screen.
#:
#: The key is the constant's name here, which couples the panel's form to this
#: module. That is a real cost and the honest one: the alternative is a second
#: vocabulary for the same screens, kept in step by hand.
EDITABLE: Final[dict[str, str]] = {
    "WELCOME_NEW": "خوش‌آمد به مشتری جدید",
    "WELCOME_BACK": "خوش‌آمد به مشتری قدیمی",
    "SHOP_INTRO": "متن بالای فروشگاه",
    "SHOP_EMPTY": "وقتی پلنی موجود نیست",
    "PLAN_TRUST": "دلایل اعتماد، زیر قیمت",
    "SUPPORT_INTRO": "متن صفحهٔ پشتیبانی",
    "FAQ_INTRO": "متن سوالات متداول",
    "PAY_CHOOSE": "بالای انتخاب روش پرداخت",
    "DASH_EMPTY": "وقتی مشتری سرویسی ندارد",
}


def placeholders(key: str) -> tuple[str, ...]:
    """Which `{name}` fields a screen's text must keep.

    A reseller who deletes `{brand}` from the welcome gets a message with no
    shop name in it, which is their business. One who deletes `{amount}` from a
    payment screen gets a customer who does not know what to transfer, which is
    not - so the panel refuses that edit rather than discovering it later.
    """
    import re

    return tuple(sorted(set(re.findall(r"{(\w+)}", getattr(T, key, "")))))


def default_for(key: str) -> str:
    return str(getattr(T, key, ""))


def resolve(scope: Any, key: str) -> str:
    """This shop's wording for one screen.

    The override when there is one, ours otherwise. Read off the scope, which
    already carries the shop - a helper taking a reseller would be one more
    argument for a handler to forget, and a forgotten one here shows a
    reseller's customer our words under their name.
    """
    texts = getattr(scope, "reseller_texts", None) or {}
    return texts.get(key) or default_for(key)


__all__ = ["EDITABLE", "default_for", "placeholders", "resolve"]
