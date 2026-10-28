"""The daily orders report as the operators read it in Telegram."""

from __future__ import annotations

from typing import Final

from geekvpn.application.analytics.daily_report import DayOrders
from geekvpn.presentation.bot.ui.fa import fa_date, fa_digits, toman

DAILY_REPORT: Final = (
    "📊 <b>گزارش روزانهٔ سفارش‌ها</b>\n"
    "{day}\n\n"
    "🧾 سفارش ثبت‌شده: <b>{placed}</b>\n"
    "✅ تحویل‌شده: {delivered}\n"
    "⏳ پرداخت‌شده، در انتظار تحویل: {waiting}\n"
    "❌ ناموفق: {failed}\n"
    "🚫 پرداخت‌نشده یا لغوشده: {unpaid}\n"
    "↩️ مسترد: {refunded}\n\n"
    "📈 نرخ موفقیت تحویل: <b>{success}</b>\n"
    "💳 نرخ پرداخت: {payment}\n\n"
    "💰 فروش امروز: <b>{revenue}</b>\n"
    "🔁 تمدید: {renewals}\n"
    "👤 کاربر جدید: {new_customers}"
)
#: Said instead of a rate on a day with nothing to divide by.
NO_RATE: Final = "—"
#: Added when paid orders are still without a service.
WAITING_HINT: Final = (
    "\n\n⚠️ {count} سفارش پول داده و سرویس نگرفته؛ از پنل «سفارش‌ها» با فیلتر «پرداخت شده» پیگیری کن."
)


def render_daily_report(day: DayOrders) -> str:
    def rate(value: int | None) -> str:
        return NO_RATE if value is None else f"{fa_digits(value)}٪"

    body = DAILY_REPORT.format(
        day=fa_date(day.day),
        placed=fa_digits(day.placed),
        delivered=fa_digits(day.delivered),
        waiting=fa_digits(day.waiting),
        failed=fa_digits(day.failed),
        unpaid=fa_digits(day.unpaid),
        refunded=fa_digits(day.refunded),
        success=rate(day.success_percent),
        payment=rate(day.payment_percent),
        revenue=toman(day.revenue),
        renewals=fa_digits(day.renewals),
        new_customers=fa_digits(day.new_customers),
    )
    stuck = day.waiting + day.failed
    if stuck:
        body += WAITING_HINT.format(count=fa_digits(stuck))
    return body
