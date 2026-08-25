"""Persian copy for the bot's operator area.

Separate from `text.py` because every string in that file is written for a
customer, and mixing the two is how a reviewer's wording ends up in front of
the person being reviewed.
"""

from __future__ import annotations

from typing import Final

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

# -- shared ----------------------------------------------------------------

BTN_BACK: Final = "⬅️ بازگشت"
ACTION_FAILED: Final = "انجام نشد: {reason}"

__all__ = [name for name in dir() if name.isupper()]
