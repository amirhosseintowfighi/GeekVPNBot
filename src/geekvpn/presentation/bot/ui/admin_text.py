"""Persian copy for the bot's operator area.

Separate from `text.py` because every string in that file is written for a
customer, and mixing the two is how a reviewer's wording ends up in front of
the person being reviewed.
"""

from __future__ import annotations

from typing import Final

MENU_BUTTON: Final = "🛠 بخش مدیریت"

MENU_TITLE: Final = (
    "🛠 <b>بخش مدیریت</b>\n\n" "کاری که می‌خواهید انجام دهید را انتخاب کنید."
)

BTN_PAYMENTS: Final = "🧾 رسیدهای در انتظار"
BTN_TICKETS: Final = "💬 تیکت‌های باز"
BTN_ADMINS: Final = "👤 ادمین‌ها"

NOT_AN_ADMIN: Final = "این بخش فقط برای مدیران است."

# -- payments --------------------------------------------------------------

PAYMENTS_EMPTY: Final = "هیچ رسیدی در انتظار بررسی نیست."
PAYMENTS_TITLE: Final = "🧾 <b>رسیدهای در انتظار بررسی</b>\n\nروی هرکدام بزنید تا رسیدش را ببینید."

PAYMENT_CARD: Final = (
    "🧾 <b>رسید پرداخت</b>\n\n"
    "مبلغ: <b>{amount}</b>\n"
    "کاربر: <code>{user_id}</code>\n"
    "کد پیگیری: <code>{reference}</code>\n"
    "ثبت‌شده: {created}"
)
PAYMENT_NO_IMAGE: Final = "برای این پرداخت تصویری ثبت نشده است."
PAYMENT_APPROVED: Final = "✅ پرداخت تأیید شد و سرویس در حال آماده‌سازی است."
PAYMENT_REJECTED: Final = "❌ پرداخت رد شد و به کاربر اطلاع داده می‌شود."
PAYMENT_ASK_REASON: Final = "علت رد شدن را بنویسید. همین متن برای کاربر فرستاده می‌شود."

BTN_APPROVE: Final = "✅ تأیید"
BTN_REJECT: Final = "❌ رد"

# -- tickets ---------------------------------------------------------------

TICKETS_EMPTY: Final = "هیچ تیکت بازی نیست."
TICKETS_TITLE: Final = "💬 <b>تیکت‌های باز</b>"

TICKET_CARD: Final = (
    "💬 <b>{subject}</b>\n\n"
    "کد: <code>{reference}</code>\n"
    "کاربر: <code>{user_id}</code>\n"
    "وضعیت: {state}\n\n"
    "{thread}"
)
TICKET_ASK_REPLY: Final = "پاسخ خود را بنویسید."
TICKET_REPLIED: Final = "✅ پاسخ ثبت شد و برای کاربر ارسال می‌شود."
TICKET_CLOSED: Final = "✅ تیکت بسته شد."

BTN_REPLY: Final = "✍️ پاسخ"
BTN_CLOSE_TICKET: Final = "🔒 بستن تیکت"

# -- admins ----------------------------------------------------------------

ADMINS_TITLE: Final = "👤 <b>ادمین‌ها</b>"
ADMINS_ROW: Final = "• <code>{username}</code> — {role}{telegram}"
BTN_ADD_ADMIN: Final = "➕ افزودن ادمین"

ADD_ADMIN_ASK_ID: Final = (
    "شناسه‌ی عددی تلگرام فرد را بفرستید.\n\n"
    "اگر نمی‌دانید، از او بخواهید یک پیام برایتان فوروارد کند و همان را اینجا فوروارد کنید."
)
ADD_ADMIN_ASK_ROLE: Final = "نقش این ادمین را انتخاب کنید."
ADD_ADMIN_BAD_ID: Final = "شناسه باید فقط عدد باشد."
ADD_ADMIN_HIDDEN_FORWARD: Final = (
    "این پیام شناسه‌ی فرستنده را همراه ندارد. تلگرام وقتی کاربر آن را در تنظیماتش "
    "بسته باشد شناسه را حذف می‌کند؛ عدد را دستی بفرستید."
)
ADD_ADMIN_DONE: Final = (
    "✅ ادمین ساخته شد.\n\n"
    "نام کاربری: <code>{username}</code>\n"
    "نقش: {role}\n\n"
    "این حساب همین حالا در ربات کار می‌کند. برای ورود به پنل وب باید رمزش از "
    "خود پنل تنظیم شود — رمز عبور هیچ‌وقت در چت فرستاده نمی‌شود."
)
ADD_ADMIN_EXISTS: Final = "این شناسه از قبل ادمین است."

ONLY_SUPER_ADMIN: Final = "فقط مدیر ارشد می‌تواند ادمین اضافه کند."

# -- customers -------------------------------------------------------------

BTN_CUSTOMER: Final = "🔍 جستجوی کاربر"
CUSTOMER_ASK_ID: Final = (
    "شناسه‌ی عددی تلگرام کاربر را بفرستید.\n\n"
    "یا پیامی از او را همین‌جا فوروارد کنید."
)
CUSTOMER_NOT_FOUND: Final = "کاربری با این شناسه پیدا نشد."
CUSTOMER_CARD: Final = (
    "👤 <b>{name}</b>\n\n"
    "شناسه: <code>{telegram_id}</code>\n"
    "نام کاربری: {username}\n"
    "وضعیت: {status}\n"
    "کیف پول: <b>{balance}</b>\n"
    "سفارش‌ها: {orders}\n"
    "اشتراک‌های فعال: {subscriptions}"
)

BTN_WALLET_ADD: Final = "💰 افزایش موجودی"
BTN_WALLET_TAKE: Final = "➖ کاهش موجودی"
BTN_MESSAGE: Final = "✉️ پیام"
BTN_SUSPEND: Final = "🚫 مسدودسازی"
BTN_REINSTATE: Final = "✅ رفع مسدودی"
BTN_SUBSCRIPTIONS: Final = "📦 اشتراک‌ها"

WALLET_ASK_AMOUNT: Final = (
    "مبلغ را به تومان بفرستید.\n\nفقط عدد، بدون جداکننده."
)
WALLET_ASK_REASON: Final = "دلیل را بنویسید. در دفتر ثبت می‌شود."
WALLET_DONE: Final = "✅ کیف پول اصلاح شد. موجودی جدید: <b>{balance}</b>"
AMOUNT_NOT_A_NUMBER: Final = "مبلغ باید فقط عدد باشد."

MESSAGE_ASK_BODY: Final = "متن پیام را بنویسید. مستقیم برای کاربر فرستاده می‌شود."
MESSAGE_SENT: Final = "✅ پیام فرستاده شد."
MESSAGE_FROM_SUPPORT: Final = "پیام پشتیبانی"

SUSPEND_ASK_REASON: Final = "علت مسدودسازی را بنویسید."
SUSPENDED: Final = "🚫 کاربر مسدود شد."
REINSTATED: Final = "✅ مسدودی برداشته شد."

# -- subscriptions ---------------------------------------------------------

SUBSCRIPTIONS_EMPTY: Final = "این کاربر اشتراکی ندارد."
SUBSCRIPTION_CARD: Final = (
    "📦 <b>{plan}</b>\n\n"
    "وضعیت: {state}\n"
    "انقضا: {expires}\n"
    "مصرف: {usage}\n"
    "سرور: <code>{node}</code>"
)
BTN_SUB_EXTEND: Final = "📅 تمدید"
BTN_SUB_TRAFFIC: Final = "➕ افزودن حجم"
BTN_SUB_SUSPEND: Final = "⏸ تعلیق"
BTN_SUB_RESUME: Final = "▶️ رفع تعلیق"
BTN_SUB_REVOKE: Final = "🗑 لغو"

SUB_ASK_DAYS: Final = "چند روز اضافه شود؟ فقط عدد."
SUB_ASK_GIB: Final = "چند گیگابایت اضافه شود؟ فقط عدد."
SUB_ASK_REASON: Final = "دلیل را بنویسید."
SUB_DONE: Final = "✅ انجام شد."
SUB_PANEL_REFUSED: Final = (
    "پنل این تغییر را نپذیرفت، پس چیزی عوض نشد:\n{reason}"
)

# -- orders ----------------------------------------------------------------

BTN_ORDERS: Final = "🧾 سفارش‌های اخیر"
ORDERS_EMPTY: Final = "سفارشی ثبت نشده است."
ORDERS_TITLE: Final = "🧾 <b>سفارش‌های اخیر</b>"
ORDER_CARD: Final = (
    "🧾 <b>{number}</b>\n\n"
    "پلن: {plan}\n"
    "مبلغ: <b>{total}</b>\n"
    "وضعیت: {state}\n"
    "کاربر: <code>{user_id}</code>\n"
    "ثبت: {placed}"
)
BTN_RETRY_PROVISION: Final = "🔄 تلاش دوباره برای تحویل"
RETRY_OK: Final = "✅ سرویس تحویل داده شد."
RETRY_FAILED: Final = "تحویل باز هم انجام نشد:\n{reason}"

# -- numbers ---------------------------------------------------------------

BTN_STATS: Final = "📊 آمار امروز"
STATS_CARD: Final = "📊 <b>{title}</b>\n\n{lines}"
STATS_ROW: Final = "• {label}: <b>{value}</b>"

# -- shared ----------------------------------------------------------------

BTN_BACK: Final = "⬅️ بازگشت"
ACTION_FAILED: Final = "انجام نشد: {reason}"

__all__ = [name for name in dir() if name.isupper()]
