"""Persian copy for the reseller area.

Its own module rather than more constants in `text.py`, because this is the
only screen in the bot whose reader is not a customer. A reseller wants
margins, credit and a link to hand over - not reassurance about delivery times.

Same register as `text.py`: second-person singular (تو) and spoken Persian. A
reseller reaches this area through the same bot that just spoke to them as a
customer, and switching to the formal voice halfway through reads as two
products stitched together.
"""

from __future__ import annotations

from typing import Any, Final

from geekvpn.presentation.bot.ui.fa import fa_date, fa_number, rtl_line, toman

# -- the invitation ---------------------------------------------------------

INVITE: Final = (

    "\U0001f91d <b>\u0646\u0645\u0627\u06cc\u0646\u062f\u06af\u06cc \u0641\u0631\u0648\u0634</b>\n"
    "\n"
    "\u0633\u0631\u0648\u06cc\u0633\u200c\u0647\u0627 \u0631\u0648 \u0639\u0645\u062f\u0647 \u0628\u06af\u06cc\u0631\u060c \u0628\u0627 \u0642\u06cc\u0645\u062a \u062e\u0648\u062f\u062a \u0628\u0641\u0631\u0648\u0634.\n"
    "\n"
    "\U0001f4b0 \u0642\u06cc\u0645\u062a \u0627\u062e\u062a\u0635\u0627\u0635\u06cc \u0631\u0648\u06cc \u0647\u0645\u0647\u0654 \u067e\u0644\u0646\u200c\u0647\u0627\n"
    "\U0001f3f7\ufe0f \u0642\u06cc\u0645\u062a \u0641\u0631\u0648\u0634 \u0631\u0648 \u062e\u0648\u062f\u062a \u062a\u0639\u06cc\u06cc\u0646 \u0645\u06cc\u200c\u06a9\u0646\u06cc\n"
    "\U0001f916 \u0631\u0628\u0627\u062a \u0627\u062e\u062a\u0635\u0627\u0635\u06cc \u0628\u0627 \u0627\u0633\u0645 \u062e\u0648\u062f\u062a\n"
    "\u26a1 \u0633\u0627\u062e\u062a \u0622\u0646\u06cc \u0633\u0631\u0648\u06cc\u0633\u060c \u0628\u062f\u0648\u0646 \u0648\u0627\u0633\u0637\u0647\n"
    "\n"
    "\u0628\u0631\u0627\u06cc \u0634\u0631\u0648\u0639\u060c \u062f\u0631\u062e\u0648\u0627\u0633\u062a\u062a \u0631\u0648 \u062b\u0628\u062a \u06a9\u0646 \u062a\u0627 \u0646\u06af\u0627\u0647\u0634 \u06a9\u0646\u06cc\u0645."

)

BTN_APPLY: Final = "📝 ثبت درخواست نمایندگی"
BTN_CANCEL: Final = "✖️ انصراف"

ASK_SHOP_NAME: Final = (

    "\u0627\u0633\u0645 \u06a9\u0633\u0628\u200c\u0648\u06a9\u0627\u0631\u062a \u0686\u06cc\u0647\u061f\n"
    "\n"
    "\u0647\u0645\u06cc\u0646 \u0627\u0633\u0645 \u0631\u0648\u06cc \u067e\u0631\u0648\u0646\u062f\u0647\u0654 \u0646\u0645\u0627\u06cc\u0646\u062f\u06af\u06cc\u062a \u062b\u0628\u062a \u0645\u06cc\u200c\u0634\u0647."

)
NAME_TOO_SHORT: Final = "\u06cc\u0647 \u06a9\u0645 \u06a9\u0648\u062a\u0627\u0647\u0647. \u06a9\u0627\u0645\u0644\u200c\u062a\u0631\u0634 \u06a9\u0646."
ASK_CONTACT: Final = (

    "\u0631\u0627\u0647 \u0627\u0631\u062a\u0628\u0627\u0637\u06cc\u062a \u0631\u0648 \u0628\u0646\u0648\u06cc\u0633 \u2014 \u0634\u0645\u0627\u0631\u0647 \u062a\u0645\u0627\u0633\u060c \u0622\u06cc\u062f\u06cc \u062a\u0644\u06af\u0631\u0627\u0645\u060c \u0647\u0631\u0686\u06cc \u0631\u0627\u062d\u062a\u200c\u062a\u0631\u06cc.\n"
    "\n"
    "\u0627\u06af\u0647 \u062a\u0648\u0636\u06cc\u062d\u06cc \u062f\u0627\u0631\u06cc (\u0645\u062b\u0644\u0627\u064b \u0627\u0644\u0627\u0646 \u0686\u0646\u062f\u062a\u0627 \u0645\u0634\u062a\u0631\u06cc \u062f\u0627\u0631\u06cc) \u0647\u0645\u0648\u0646\u200c\u062c\u0627 \u0627\u0636\u0627\u0641\u0647 \u06a9\u0646."

)
APPLICATION_SENT: Final = (

    "\u2705 \u062f\u0631\u062e\u0648\u0627\u0633\u062a\u062a \u062b\u0628\u062a \u0634\u062f.\n"
    "\n"
    "\u0632\u0648\u062f \u0628\u0631\u0631\u0633\u06cc\u0634 \u0645\u06cc\u200c\u06a9\u0646\u06cc\u0645 \u0648 \u0646\u062a\u06cc\u062c\u0647 \u0631\u0648 \u0647\u0645\u06cc\u0646\u200c\u062c\u0627 \u0628\u0647\u062a \u0645\u06cc\u200c\u06af\u06cc\u0645."

)
APPLICATION_PENDING: Final = (

    "\u23f3 \u062f\u0631\u062e\u0648\u0627\u0633\u062a \u0646\u0645\u0627\u06cc\u0646\u062f\u06af\u06cc\u062a \u062f\u0631 \u062d\u0627\u0644 \u0628\u0631\u0631\u0633\u06cc\u0647.\n"
    "\n"
    "\u0628\u0647 \u0645\u062d\u0636 \u0627\u06cc\u0646\u06a9\u0647 \u062a\u0635\u0645\u06cc\u0645 \u06af\u0631\u0641\u062a\u06cc\u0645\u060c \u0647\u0645\u06cc\u0646\u200c\u062c\u0627 \u062e\u0628\u0631\u062a \u0645\u06cc\u200c\u06a9\u0646\u06cc\u0645."

)

# -- the console ------------------------------------------------------------

CONSOLE: Final = (

    "\U0001f91d <b>{name}</b>\n"
    "\n"
    "{state}\n"
    "\U0001f3f7\ufe0f \u062a\u062e\u0641\u06cc\u0641\u062a: {discount}\u066a\n"
    ""

)
CONSOLE_BALANCE: Final = "💰 اعتبار: {balance}"
CONSOLE_ARREARS: Final = (

    "\U0001f534 <b>\u0628\u062f\u0647\u06cc: {debt}</b>\n"
    "\u0633\u0631\u0648\u06cc\u0633 \u0645\u0634\u062a\u0631\u06cc\u200c\u0647\u0627\u062a \u062a\u0627 \u062a\u0633\u0648\u06cc\u0647 \u063a\u06cc\u0631\u0641\u0639\u0627\u0644\u0647 \u0648 \u0628\u0644\u0627\u0641\u0627\u0635\u0644\u0647 \u0628\u0639\u062f \u0627\u0632 \u067e\u0631\u062f\u0627\u062e\u062a \u0628\u0631\u0645\u06cc\u200c\u06af\u0631\u062f\u0647."

)

BTN_SELL: Final = "⚡ ساخت سرویس"
BTN_PRICES: Final = "🏷️ قیمت‌ها"
BTN_LEDGER: Final = "🧾 گردش اعتبار"
BTN_SET_PRICE: Final = "✏️ تغییر قیمت فروش"

NOT_A_RESELLER: Final = "\u0627\u06cc\u0646 \u0628\u062e\u0634 \u0645\u0627\u0644 \u0646\u0645\u0627\u06cc\u0646\u062f\u0647\u200c\u0647\u0627\u0633\u062a."
SUSPENDED: Final = "\u062d\u0633\u0627\u0628 \u0646\u0645\u0627\u06cc\u0646\u062f\u06af\u06cc\u062a \u0641\u0639\u0644\u0627\u064b \u0645\u0639\u0644\u0642\u0647. \u0628\u0627 \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc \u062a\u0645\u0627\u0633 \u0628\u06af\u06cc\u0631."
NO_PLANS: Final = "\u0641\u0639\u0644\u0627\u064b \u067e\u0644\u0646\u06cc \u0628\u0631\u0627\u06cc \u0641\u0631\u0648\u0634 \u0646\u06cc\u0633\u062a."
CHOOSE_PLAN: Final = (
    "\u06a9\u062f\u0648\u0645 \u067e\u0644\u0646 \u0631\u0648 \u0645\u06cc\u200c\u0633\u0627\u0632\u06cc\u061f\n"
    "\n"
    "\u0645\u0628\u0644\u063a\u0634 \u0627\u0632 \u0627\u0639\u062a\u0628\u0627\u0631\u062a \u06a9\u0645 \u0645\u06cc\u200c\u0634\u0647."
)
PLAN_GONE: Final = "\u0627\u06cc\u0646 \u067e\u0644\u0646 \u062f\u06cc\u06af\u0647 \u0645\u0648\u062c\u0648\u062f \u0646\u06cc\u0633\u062a."
NOT_ENOUGH_CREDIT: Final = (

    "\u274c \u0627\u0639\u062a\u0628\u0627\u0631\u062a \u06a9\u0627\u0641\u06cc \u0646\u06cc\u0633\u062a.\n"
    "\n"
    "{shortfall} \u06a9\u0645 \u062f\u0627\u0631\u06cc."

)


def price_table(rows: list[dict[str, Any]]) -> str:
    """Cost beside retail, package by package.

    Both numbers on one screen because a reseller choosing what to charge is
    comparing their margin - and a screen showing one of the two is a screen
    they price from memory against.
    """
    lines = [rtl_line("🏷️ <b>قیمت‌های تو</b>"), ""]
    for row in rows:
        margin = int(row["retail"]) - int(row["cost"])
        lines.append(rtl_line(f"<b>{row['name']}</b> · {fa_number(row['duration_days'])} روز"))
        lines.append(rtl_line(f"  خرید تو: {toman(int(row['cost']))}"))
        lines.append(rtl_line(f"  فروش تو: {toman(int(row['retail']))}"))
        lines.append(rtl_line(f"  سود: {toman(margin)}" if margin >= 0 else "  ⚠️ زیر قیمت خرید"))
        lines.append("")
    lines.append(rtl_line("قیمت فروش رو از پنل یا با دکمهٔ زیر عوض کن."))
    return "\n".join(lines)


def plan_button(row: dict[str, Any]) -> str:
    return f"{row['name']} · {toman(int(row['cost']))}"


def ledger(entries: Any) -> str:
    lines = [rtl_line("🧾 <b>گردش اعتبار</b>"), ""]
    rows = list(entries)
    if not rows:
        return "\n".join([*lines, rtl_line("هنوز تراکنشی نداری.")])
    for entry in rows:
        sign = "−" if entry.amount < 0 else "+"
        lines.append(
            rtl_line(
                f"{sign}{toman(abs(entry.amount))} · {entry.description_fa}"
            )
        )
        lines.append(rtl_line(f"  مانده: {toman(entry.balance_after)} · {fa_date(entry.occurred_at)}"))
    return "\n".join(lines)


def sold(sale: Any, *, plan_name: str) -> str:
    """The link, and the number that changed - the two things they need next.

    The subscription link is what they hand their customer, and the balance is
    what tells them whether they can make the next sale without topping up.
    """
    body = [
        rtl_line("✅ <b>سرویس ساخته شد</b>"),
        "",
        rtl_line(f"📦 {plan_name}"),
        rtl_line(f"💳 کسر شد: {toman(sale.charged.amount)}"),
        rtl_line(f"💰 اعتبار باقی‌مونده: {toman(sale.balance_after)}"),
        "",
    ]
    if sale.subscription_url:
        body.append(rtl_line("🔗 <b>لینک اشتراک مشتریت:</b>"))
        body.append(f"<code>{sale.subscription_url}</code>")
    else:
        # The account exists; the panel just has not answered with its link
        # yet. Saying so beats an empty space where a link should be.
        body.append(rtl_line("لینک اتصال تا چند لحظهٔ دیگه تو پنل آماده می‌شه."))
    return "\n".join(body)


__all__ = [
    "APPLICATION_PENDING",
    "APPLICATION_SENT",
    "ASK_CONTACT",
    "ASK_SHOP_NAME",
    "BTN_APPLY",
    "BTN_CANCEL",
    "BTN_LEDGER",
    "BTN_PRICES",
    "BTN_SELL",
    "BTN_SET_PRICE",
    "CHOOSE_PLAN",
    "CONSOLE",
    "CONSOLE_ARREARS",
    "CONSOLE_BALANCE",
    "INVITE",
    "NAME_TOO_SHORT",
    "NOT_A_RESELLER",
    "NOT_ENOUGH_CREDIT",
    "NO_PLANS",
    "PLAN_GONE",
    "SUSPENDED",
    "ledger",
    "plan_button",
    "price_table",
    "sold",
]
