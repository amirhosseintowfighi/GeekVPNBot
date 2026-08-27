"""Persian copy for the reseller area.

Its own module rather than more constants in `text.py`, because this is the
only screen in the bot whose reader is not a customer. A reseller wants
margins, credit and a link to hand over - not reassurance about delivery times.
"""

from __future__ import annotations

from typing import Any, Final

from geekvpn.presentation.bot.ui.fa import fa_date, fa_number, rtl_line, toman

# -- the invitation ---------------------------------------------------------

INVITE: Final = (
    "🤝 <b>نمایندگی فروش</b>\n\n"
    "سرویس‌ها را با قیمت عمده بگیرید و با قیمت خودتان بفروشید.\n\n"
    "💰 قیمت اختصاصی روی همهٔ پلن‌ها\n"
    "🏷️ قیمت فروش را خودتان تعیین می‌کنید\n"
    "🤖 ربات اختصاصی با نام خودتان\n"
    "⚡ ساخت آنی سرویس، بدون واسطه\n\n"
    "برای شروع، درخواستتان را ثبت کنید تا بررسی کنیم."
)

BTN_APPLY: Final = "📝 ثبت درخواست نمایندگی"
BTN_CANCEL: Final = "✖️ انصراف"

ASK_SHOP_NAME: Final = (
    "نام کسب‌وکارتان چیست؟\n\nهمین نام روی پرونده‌ی نمایندگی شما ثبت می‌شود."
)
NAME_TOO_SHORT: Final = "نام کوتاه است. کمی کامل‌ترش کنید."
ASK_CONTACT: Final = (
    "راه ارتباطی‌تان را بنویسید — شماره تماس، آیدی تلگرام، هر چه راحت‌ترید.\n\n"
    "اگر توضیحی دارید (مثلاً الان چند مشتری دارید) همان‌جا اضافه کنید."
)
APPLICATION_SENT: Final = (
    "✅ درخواست شما ثبت شد.\n\n"
    "به‌زودی بررسی می‌کنیم و نتیجه را همین‌جا اطلاع می‌دهیم."
)
APPLICATION_PENDING: Final = (
    "⏳ درخواست نمایندگی شما در حال بررسی است.\n\n"
    "به محض تصمیم‌گیری همین‌جا خبرتان می‌کنیم."
)

# -- the console ------------------------------------------------------------

CONSOLE: Final = (
    "🤝 <b>{name}</b>\n\n"
    "{state}\n"
    "🏷️ تخفیف شما: {discount}٪\n"
)
CONSOLE_BALANCE: Final = "💰 اعتبار: {balance}"
CONSOLE_ARREARS: Final = (
    "🔴 <b>بدهی: {debt}</b>\n"
    "سرویس مشتریان شما تا تسویه غیرفعال است و بلافاصله بعد از پرداخت برمی‌گردد."
)

BTN_SELL: Final = "⚡ ساخت سرویس"
BTN_PRICES: Final = "🏷️ قیمت‌ها"
BTN_LEDGER: Final = "🧾 گردش اعتبار"
BTN_SET_PRICE: Final = "✏️ تغییر قیمت فروش"

NOT_A_RESELLER: Final = "این بخش برای نمایندگان است."
SUSPENDED: Final = "حساب نمایندگی شما فعلاً معلق است. با پشتیبانی تماس بگیرید."
NO_PLANS: Final = "فعلاً پلنی برای فروش موجود نیست."
CHOOSE_PLAN: Final = "کدام پلن را می‌سازید؟\n\nمبلغ از اعتبار شما کم می‌شود."
PLAN_GONE: Final = "این پلن دیگر موجود نیست."
NOT_ENOUGH_CREDIT: Final = (
    "❌ اعتبارتان کافی نیست.\n\nحداقل {shortfall} کم دارید."
)


def price_table(rows: list[dict[str, Any]]) -> str:
    """Cost beside retail, package by package.

    Both numbers on one screen because a reseller choosing what to charge is
    comparing their margin - and a screen showing one of the two is a screen
    they price from memory against.
    """
    lines = [rtl_line("🏷️ <b>قیمت‌های شما</b>"), ""]
    for row in rows:
        margin = int(row["retail"]) - int(row["cost"])
        lines.append(rtl_line(f"<b>{row['name']}</b> · {fa_number(row['duration_days'])} روز"))
        lines.append(rtl_line(f"  خرید شما: {toman(int(row['cost']))}"))
        lines.append(rtl_line(f"  فروش شما: {toman(int(row['retail']))}"))
        lines.append(rtl_line(f"  سود: {toman(margin)}" if margin >= 0 else "  ⚠️ زیر قیمت خرید"))
        lines.append("")
    lines.append(rtl_line("قیمت فروش را از پنل یا با دکمهٔ زیر تغییر دهید."))
    return "\n".join(lines)


def plan_button(row: dict[str, Any]) -> str:
    return f"{row['name']} · {toman(int(row['cost']))}"


def ledger(entries: Any) -> str:
    lines = [rtl_line("🧾 <b>گردش اعتبار</b>"), ""]
    rows = list(entries)
    if not rows:
        return "\n".join([*lines, rtl_line("هنوز تراکنشی ثبت نشده.")])
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
        rtl_line(f"💰 اعتبار باقی‌مانده: {toman(sale.balance_after)}"),
        "",
    ]
    if sale.subscription_url:
        body.append(rtl_line("🔗 <b>لینک اشتراک برای مشتری شما:</b>"))
        body.append(f"<code>{sale.subscription_url}</code>")
    else:
        # The account exists; the panel just has not answered with its link
        # yet. Saying so beats an empty space where a link should be.
        body.append(rtl_line("لینک اتصال تا لحظاتی دیگر در پنل آماده می‌شود."))
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
