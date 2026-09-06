"""Persian copy for the bot's operator area.

Separate from `text.py` because every string in that file is written for a
customer, and mixing the two is how a reviewer's wording ends up in front of
the person being reviewed.

Same register as `text.py` and `reseller_text.py`: second-person singular and
spoken Persian. Separate audience, one voice.

The one place that stays exact rather than breezy is what an operator is told
about a new admin's password - that it is set from the panel and never sent
through chat. A relaxed wording there invites somebody to type one into
Telegram.
"""

from __future__ import annotations

from typing import Final

MENU_BUTTON: Final = "🛠 بخش مدیریت"

MENU_TITLE: Final = (

    "\U0001f6e0 <b>\u0628\u062e\u0634 \u0645\u062f\u06cc\u0631\u06cc\u062a</b>\n"
    "\n"
    "\u0686\u06cc \u06a9\u0627\u0631 \u0645\u06cc\u200c\u062e\u0648\u0627\u06cc \u0628\u06a9\u0646\u06cc\u061f"

)

BTN_PAYMENTS: Final = "🧾 رسیدهای در انتظار"
BTN_TICKETS: Final = "💬 تیکت‌های باز"
BTN_ADMINS: Final = "👤 ادمین‌ها"

NOT_AN_ADMIN: Final = "\u0627\u06cc\u0646 \u0628\u062e\u0634 \u0641\u0642\u0637 \u0645\u0627\u0644 \u0645\u062f\u06cc\u0631\u0647\u0627\u0633\u062a."

# -- payments --------------------------------------------------------------

PAYMENTS_EMPTY: Final = "\u0647\u06cc\u0686 \u0631\u0633\u06cc\u062f\u06cc \u0645\u0646\u062a\u0638\u0631 \u0628\u0631\u0631\u0633\u06cc \u0646\u06cc\u0633\u062a."
PAYMENTS_TITLE: Final = (
    "\U0001f9fe <b>\u0631\u0633\u06cc\u062f\u0647\u0627\u06cc \u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 \u0628\u0631\u0631\u0633\u06cc</b>\n"
    "\n"
    "\u0631\u0648\u06cc \u0647\u0631 \u06a9\u062f\u0648\u0645 \u0628\u0632\u0646\u06cc \u0631\u0633\u06cc\u062f\u0634 \u0631\u0648 \u0645\u06cc\u200c\u0628\u06cc\u0646\u06cc."
)

PAYMENT_CARD: Final = (
    "🧾 <b>رسید پرداخت</b>\n\n"
    "مبلغ: <b>{amount}</b>\n"
    "کاربر: <code>{user_id}</code>\n"
    "کد پیگیری: <code>{reference}</code>\n"
    "ثبت‌شده: {created}"
)
PAYMENT_NO_IMAGE: Final = "\u0628\u0631\u0627\u06cc \u0627\u06cc\u0646 \u067e\u0631\u062f\u0627\u062e\u062a \u062a\u0635\u0648\u06cc\u0631\u06cc \u062b\u0628\u062a \u0646\u0634\u062f\u0647."
PAYMENT_APPROVED: Final = "\u2705 \u067e\u0631\u062f\u0627\u062e\u062a \u062a\u0623\u06cc\u06cc\u062f \u0634\u062f\u060c \u0633\u0631\u0648\u06cc\u0633 \u062f\u0627\u0631\u0647 \u0622\u0645\u0627\u062f\u0647 \u0645\u06cc\u200c\u0634\u0647."
PAYMENT_REJECTED: Final = "\u274c \u067e\u0631\u062f\u0627\u062e\u062a \u0631\u062f \u0634\u062f \u0648 \u0628\u0647 \u06a9\u0627\u0631\u0628\u0631 \u062e\u0628\u0631 \u062f\u0627\u062f\u0647 \u0645\u06cc\u200c\u0634\u0647."
PAYMENT_ASK_REASON: Final = "\u0639\u0644\u062a \u0631\u062f \u0634\u062f\u0646 \u0631\u0648 \u0628\u0646\u0648\u06cc\u0633. \u0647\u0645\u06cc\u0646 \u0645\u062a\u0646 \u0628\u0631\u0627\u06cc \u06a9\u0627\u0631\u0628\u0631 \u0645\u06cc\u200c\u0631\u0647."

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
TICKET_ASK_REPLY: Final = "\u067e\u0627\u0633\u062e\u062a \u0631\u0648 \u0628\u0646\u0648\u06cc\u0633."
TICKET_REPLIED: Final = "\u2705 \u067e\u0627\u0633\u062e \u062b\u0628\u062a \u0634\u062f \u0648 \u0628\u0631\u0627\u06cc \u06a9\u0627\u0631\u0628\u0631 \u0645\u06cc\u200c\u0631\u0647."
TICKET_CLOSED: Final = "✅ تیکت بسته شد."

BTN_REPLY: Final = "✍️ پاسخ"
BTN_CLOSE_TICKET: Final = "🔒 بستن تیکت"

# -- admins ----------------------------------------------------------------

ADMINS_TITLE: Final = "👤 <b>ادمین‌ها</b>"
ADMINS_ROW: Final = "• <code>{username}</code> — {role}{telegram}"
BTN_ADD_ADMIN: Final = "➕ افزودن ادمین"

ADD_ADMIN_ASK_ID: Final = (

    "\u0634\u0646\u0627\u0633\u0647\u0654 \u0639\u062f\u062f\u06cc \u062a\u0644\u06af\u0631\u0627\u0645 \u0637\u0631\u0641 \u0631\u0648 \u0628\u0641\u0631\u0633\u062a.\n"
    "\n"
    "\u0627\u06af\u0647 \u0646\u0645\u06cc\u200c\u062f\u0648\u0646\u06cc\u060c \u0627\u0632\u0634 \u0628\u062e\u0648\u0627\u0647 \u06cc\u0647 \u067e\u06cc\u0627\u0645 \u0628\u0631\u0627\u062a \u0641\u0648\u0631\u0648\u0627\u0631\u062f \u06a9\u0646\u0647 \u0648 \u0647\u0645\u0648\u0646 \u0631\u0648 \u0627\u06cc\u0646\u062c\u0627 \u0641\u0648\u0631\u0648\u0627\u0631\u062f \u06a9\u0646."

)
ADD_ADMIN_ASK_ROLE: Final = "\u0646\u0642\u0634 \u0627\u06cc\u0646 \u0627\u062f\u0645\u06cc\u0646 \u0631\u0648 \u0627\u0646\u062a\u062e\u0627\u0628 \u06a9\u0646."
ADD_ADMIN_BAD_ID: Final = "\u0634\u0646\u0627\u0633\u0647 \u0628\u0627\u06cc\u062f \u0641\u0642\u0637 \u0639\u062f\u062f \u0628\u0627\u0634\u0647."
ADD_ADMIN_HIDDEN_FORWARD: Final = (
    "\u0627\u06cc\u0646 \u067e\u06cc\u0627\u0645 \u0634\u0646\u0627\u0633\u0647\u0654 \u0641\u0631\u0633\u062a\u0646\u062f\u0647 \u0631\u0648 \u0647\u0645\u0631\u0627\u0647 \u0646\u062f\u0627\u0631\u0647. \u062a\u0644\u06af\u0631\u0627\u0645 \u0648\u0642\u062a\u06cc \u06a9\u0627\u0631\u0628\u0631 \u062a\u0648 \u062a\u0646\u0638\u06cc\u0645\u0627\u062a\u0634 \u0628\u0633\u062a\u0647 \u0628\u0627\u0634\u0647 \u0634\u0646\u0627\u0633\u0647 \u0631\u0648 \u062d\u0630\u0641 \u0645\u06cc\u200c\u06a9\u0646\u0647\u061b \u0639\u062f\u062f \u0631\u0648 \u062f\u0633\u062a\u06cc \u0628\u0641\u0631\u0633\u062a."
)
ADD_ADMIN_DONE: Final = (

    "\u2705 \u0627\u062f\u0645\u06cc\u0646 \u0633\u0627\u062e\u062a\u0647 \u0634\u062f.\n"
    "\n"
    "\u0646\u0627\u0645 \u06a9\u0627\u0631\u0628\u0631\u06cc: <code>{username}</code>\n"
    "\u0646\u0642\u0634: {role}\n"
    "\n"
    "\u0627\u06cc\u0646 \u062d\u0633\u0627\u0628 \u0647\u0645\u06cc\u0646 \u062d\u0627\u0644\u0627 \u062a\u0648 \u0631\u0628\u0627\u062a \u06a9\u0627\u0631 \u0645\u06cc\u200c\u06a9\u0646\u0647. \u0628\u0631\u0627\u06cc \u0648\u0631\u0648\u062f \u0628\u0647 \u067e\u0646\u0644 \u0648\u0628 \u0628\u0627\u06cc\u062f \u0631\u0645\u0632\u0634 \u0627\u0632 \u062e\u0648\u062f \u067e\u0646\u0644 \u062a\u0646\u0638\u06cc\u0645 \u0628\u0634\u0647 \u2014 \u0631\u0645\u0632 \u0639\u0628\u0648\u0631 \u0647\u06cc\u0686\u200c\u0648\u0642\u062a \u062a\u0648 \u0686\u062a \u0641\u0631\u0633\u062a\u0627\u062f\u0647 \u0646\u0645\u06cc\u200c\u0634\u0647."

)
ADD_ADMIN_EXISTS: Final = "\u0627\u06cc\u0646 \u0634\u0646\u0627\u0633\u0647 \u0627\u0632 \u0642\u0628\u0644 \u0627\u062f\u0645\u06cc\u0646\u0647."

ONLY_SUPER_ADMIN: Final = "\u0641\u0642\u0637 \u0645\u062f\u06cc\u0631 \u0627\u0631\u0634\u062f \u0645\u06cc\u200c\u062a\u0648\u0646\u0647 \u0627\u062f\u0645\u06cc\u0646 \u0627\u0636\u0627\u0641\u0647 \u06a9\u0646\u0647."

# -- customers -------------------------------------------------------------

BTN_CUSTOMER: Final = "🔍 جستجوی کاربر"
CUSTOMER_ASK_ID: Final = (

    "\u0634\u0646\u0627\u0633\u0647\u0654 \u0639\u062f\u062f\u06cc \u062a\u0644\u06af\u0631\u0627\u0645 \u06a9\u0627\u0631\u0628\u0631 \u0631\u0648 \u0628\u0641\u0631\u0633\u062a.\n"
    "\n"
    "\u06cc\u0627 \u06cc\u0647 \u067e\u06cc\u0627\u0645 \u0627\u0632 \u062e\u0648\u062f\u0634 \u0631\u0648 \u0647\u0645\u06cc\u0646\u200c\u062c\u0627 \u0641\u0648\u0631\u0648\u0627\u0631\u062f \u06a9\u0646."

)
CUSTOMER_NOT_FOUND: Final = "\u06a9\u0627\u0631\u0628\u0631\u06cc \u0628\u0627 \u0627\u06cc\u0646 \u0634\u0646\u0627\u0633\u0647 \u067e\u06cc\u062f\u0627 \u0646\u0634\u062f."
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

    "\u0645\u0628\u0644\u063a \u0631\u0648 \u0628\u0647 \u062a\u0648\u0645\u0627\u0646 \u0628\u0641\u0631\u0633\u062a.\n"
    "\n"
    "\u0641\u0642\u0637 \u0639\u062f\u062f\u060c \u0628\u062f\u0648\u0646 \u062c\u062f\u0627\u06a9\u0646\u0646\u062f\u0647."

)
WALLET_ASK_REASON: Final = "\u062f\u0644\u06cc\u0644\u0634 \u0631\u0648 \u0628\u0646\u0648\u06cc\u0633. \u062a\u0648 \u062f\u0641\u062a\u0631 \u062b\u0628\u062a \u0645\u06cc\u200c\u0634\u0647."
WALLET_DONE: Final = "✅ کیف پول اصلاح شد. موجودی جدید: <b>{balance}</b>"
AMOUNT_NOT_A_NUMBER: Final = "\u0645\u0628\u0644\u063a \u0628\u0627\u06cc\u062f \u0641\u0642\u0637 \u0639\u062f\u062f \u0628\u0627\u0634\u0647."

MESSAGE_ASK_BODY: Final = "\u0645\u062a\u0646 \u067e\u06cc\u0627\u0645 \u0631\u0648 \u0628\u0646\u0648\u06cc\u0633. \u0645\u0633\u062a\u0642\u06cc\u0645 \u0628\u0631\u0627\u06cc \u06a9\u0627\u0631\u0628\u0631 \u0645\u06cc\u200c\u0631\u0647."
MESSAGE_SENT: Final = "✅ پیام فرستاده شد."
MESSAGE_FROM_SUPPORT: Final = "پیام پشتیبانی"

SUSPEND_ASK_REASON: Final = "\u0639\u0644\u062a \u0645\u0633\u062f\u0648\u062f\u0633\u0627\u0632\u06cc \u0631\u0648 \u0628\u0646\u0648\u06cc\u0633."
SUSPENDED: Final = "🚫 کاربر مسدود شد."
REINSTATED: Final = "✅ مسدودی برداشته شد."

# -- subscriptions ---------------------------------------------------------

SUBSCRIPTIONS_EMPTY: Final = "\u0627\u06cc\u0646 \u06a9\u0627\u0631\u0628\u0631 \u0627\u0634\u062a\u0631\u0627\u06a9\u06cc \u0646\u062f\u0627\u0631\u0647."
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

SUB_ASK_DAYS: Final = "\u0686\u0646\u062f \u0631\u0648\u0632 \u0627\u0636\u0627\u0641\u0647 \u0628\u0634\u0647\u061f \u0641\u0642\u0637 \u0639\u062f\u062f."
SUB_ASK_GIB: Final = "\u0686\u0646\u062f \u06af\u06cc\u06af\u0627\u0628\u0627\u06cc\u062a \u0627\u0636\u0627\u0641\u0647 \u0628\u0634\u0647\u061f \u0641\u0642\u0637 \u0639\u062f\u062f."
SUB_ASK_REASON: Final = "\u062f\u0644\u06cc\u0644\u0634 \u0631\u0648 \u0628\u0646\u0648\u06cc\u0633."
SUB_DONE: Final = "✅ انجام شد."
SUB_PANEL_REFUSED: Final = (

    "\u067e\u0646\u0644 \u0627\u06cc\u0646 \u062a\u063a\u06cc\u06cc\u0631 \u0631\u0648 \u0642\u0628\u0648\u0644 \u0646\u06a9\u0631\u062f\u060c \u067e\u0633 \u0686\u06cc\u0632\u06cc \u0639\u0648\u0636 \u0646\u0634\u062f:\n"
    "{reason}"

)

# -- orders ----------------------------------------------------------------

BTN_ORDERS: Final = "🧾 سفارش‌های اخیر"
ORDERS_EMPTY: Final = "\u0633\u0641\u0627\u0631\u0634\u06cc \u062b\u0628\u062a \u0646\u0634\u062f\u0647."
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
RETRY_FAILED: Final = (
    "\u062a\u062d\u0648\u06cc\u0644 \u0628\u0627\u0632 \u0647\u0645 \u0646\u0634\u062f:\n"
    "{reason}"
)

# -- numbers ---------------------------------------------------------------

BTN_STATS: Final = "📊 آمار امروز"
STATS_CARD: Final = "📊 <b>{title}</b>\n\n{lines}"
STATS_ROW: Final = "• {label}: <b>{value}</b>"

# -- shared ----------------------------------------------------------------

BTN_BACK: Final = "⬅️ بازگشت"
ACTION_FAILED: Final = "انجام نشد: {reason}"

__all__ = [name for name in dir() if name.isupper()]

# -- reseller applications --------------------------------------------------

BTN_APPLICATIONS: Final = "🤝 درخواست‌های نمایندگی"
BTN_TOPUPS: Final = "\U0001f4b0 شارژ نمایندگان"

TOPUPS_TITLE: Final = "\U0001f4b0 <b>درخواست‌های شارژ</b>"
TOPUPS_EMPTY: Final = "\u062f\u0631\u062e\u0648\u0627\u0633\u062a \u0634\u0627\u0631\u0698\u06cc \u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 \u0646\u06cc\u0633\u062a."
#: Amount first: it is the number an operator is checking against a receipt,
#: and the name only matters once they have found the right amount.
TOPUP_ROW: Final = "{amount} — {name}"
TOPUP_DETAIL: Final = (

    "\U0001f4b0 <b>\u062f\u0631\u062e\u0648\u0627\u0633\u062a \u0634\u0627\u0631\u0698</b>\n"
    "\n"
    "\U0001f3e2 \u0646\u0645\u0627\u06cc\u0646\u062f\u0647: {name}\n"
    "\U0001f4b3 \u0645\u0628\u0644\u063a: <b>{amount}</b>\n"
    "\U0001f4dd \u062a\u0648\u0636\u06cc\u062d: {note}\n"
    "\U0001f4b5 \u0627\u0639\u062a\u0628\u0627\u0631 \u0641\u0639\u0644\u06cc: {balance}\n"
    "\n"
    "\u062a\u0623\u06cc\u06cc\u062f\u0634 \u06a9\u0646\u06cc\u060c \u0647\u0645\u0648\u0646 \u0644\u062d\u0638\u0647 \u0628\u0647 \u0627\u0639\u062a\u0628\u0627\u0631\u0634 \u0627\u0636\u0627\u0641\u0647 \u0645\u06cc\u200c\u0634\u0647."

)
TOPUP_APPROVED: Final = "\u2705 شارژ {amount} برای {name} تأیید شد."
TOPUP_REJECTED: Final = "\u274c درخواست رد شد."
TOPUP_GONE: Final = "\u0627\u06cc\u0646 \u062f\u0631\u062e\u0648\u0627\u0633\u062a \u062f\u06cc\u06af\u0647 \u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 \u0646\u06cc\u0633\u062a."
APPLICATIONS_TITLE: Final = "🤝 <b>درخواست‌های نمایندگی</b>"
APPLICATIONS_EMPTY: Final = "\u062f\u0631\u062e\u0648\u0627\u0633\u062a\u06cc \u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 \u0628\u0631\u0631\u0633\u06cc \u0646\u06cc\u0633\u062a."
APPLICATION_ROW: Final = "{name} — {contact}"
APPLICATION_DETAIL: Final = (
    "🤝 <b>{name}</b>\n\n"
    "👤 شناسه تلگرام: <code>{telegram_id}</code>\n"
    "📞 تماس: {contact}\n"
    "📅 ثبت: {when}\n\n"
    "{note}"
)
BTN_APPROVE_APPLICATION: Final = "✅ تأیید نمایندگی"
BTN_REJECT_APPLICATION: Final = "❌ رد درخواست"
#: The one message in the operator area that carries a live credential.
#:
#: It is a link, not a password: single-use, expiring, and useless once spent.
#: The operator forwards it to the applicant, so it exists in exactly two
#: chats and stops working after the first tap.
APPLICATION_APPROVED: Final = (

    "\u2705 \u0646\u0645\u0627\u06cc\u0646\u062f\u06af\u06cc <b>{name}</b> \u062a\u0623\u06cc\u06cc\u062f \u0634\u062f.\n"
    "\n"
    "\U0001f511 \u0646\u0627\u0645 \u06a9\u0627\u0631\u0628\u0631\u06cc \u067e\u0646\u0644: <code>{username}</code>\n"
    "\n"
    "\u0627\u06cc\u0646 \u0644\u06cc\u0646\u06a9 \u0631\u0648 \u0628\u0631\u0627\u0634 \u0628\u0641\u0631\u0633\u062a \u062a\u0627 \u0631\u0645\u0632 \u067e\u0646\u0644\u0634 \u0631\u0648 \u062e\u0648\u062f\u0634 \u0628\u0633\u0627\u0632\u0647. \u06cc\u06a9\u200c\u0628\u0627\u0631 \u0645\u0635\u0631\u0641\u0647 \u0648 \u062a\u0627 \u06f2\u06f4 \u0633\u0627\u0639\u062a \u0627\u0639\u062a\u0628\u0627\u0631 \u062f\u0627\u0631\u0647:\n"
    "<code>{link}</code>\n"
    "\n"
    "\u062a\u0648 \u0631\u0628\u0627\u062a \u0647\u0645 \u0627\u0632 \u0647\u0645\u06cc\u0646 \u062d\u0627\u0644\u0627 \u0628\u0627 \u0647\u0645\u0648\u0646 \u062d\u0633\u0627\u0628 \u062a\u0644\u06af\u0631\u0627\u0645 \u0648\u0627\u0631\u062f \u0628\u062e\u0634 \u0646\u0645\u0627\u06cc\u0646\u062f\u06af\u06cc \u0645\u06cc\u200c\u0634\u0647."

)
APPLICATION_REJECTED: Final = "درخواست رد شد."
APPLICATION_GONE: Final = "\u0627\u06cc\u0646 \u062f\u0631\u062e\u0648\u0627\u0633\u062a \u062f\u06cc\u06af\u0647 \u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 \u0646\u06cc\u0633\u062a."
