"""Persian message catalogue and rendering.

Every user-visible string the engine can emit lives here, in Persian, keyed by
a stable template key. Schedulers and services pass *facts* (a plan name, a
number of days) and never build copy themselves. That is what makes
"everything supports Persian" verifiable: there is exactly one place to audit,
and a test can assert that no template contains a Latin letter.

Numbers are converted to Persian digits during rendering, so a caller passing
``days=3`` gets \u06f3 without having to remember. Amounts are grouped with the
Persian thousands separator U+066C.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Any

from geekvpn.domain.notifications.enums import NotificationCategory
from geekvpn.domain.notifications.errors import (
    MissingTemplateField,
    TemplateNotFound,
)

PERSIAN_DIGITS = "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9"
ASCII_DIGITS = "0123456789"
THOUSANDS_SEP = "\u066c"
DECIMAL_SEP = "\u066b"

_TO_PERSIAN = str.maketrans(ASCII_DIGITS, PERSIAN_DIGITS)

TOMAN = "\u062a\u0648\u0645\u0627\u0646"
GIB = "\u06af\u06cc\u06af\u0627\u0628\u0627\u06cc\u062a"
UNLIMITED = "\u0646\u0627\u0645\u062d\u062f\u0648\u062f"

PREVIEW_LIMIT = 120


def fa_digits(value: object) -> str:
    """Latin digits to Persian digits, leaving everything else untouched."""
    return str(value).translate(_TO_PERSIAN)


def fa_number(value: int) -> str:
    """Grouped Persian number, e.g. 680000 -> \u06f6\u06f8\u06f0\u066c\u06f0\u06f0\u06f0."""
    grouped = f"{int(value):,}".replace(",", THOUSANDS_SEP)
    return grouped.translate(_TO_PERSIAN)


def fa_toman(value: int) -> str:
    return f"{fa_number(value)} {TOMAN}"


def fa_gib(value: float | None) -> str:
    """None means an unmetered plan, which reads as \u0646\u0627\u0645\u062d\u062f\u0648\u062f, not zero."""
    if value is None:
        return UNLIMITED
    if float(value).is_integer():
        return f"{fa_number(int(value))} {GIB}"
    text = f"{float(value):.1f}".replace(".", DECIMAL_SEP)
    return f"{text.translate(_TO_PERSIAN)} {GIB}"


def _auto_format(value: Any) -> str:
    """Persian-ise a placeholder value.

    Booleans are excluded from the int branch deliberately: ``True`` is an
    ``int`` in Python and would otherwise render as \u06f1.
    """
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return fa_number(value)
    if isinstance(value, float):
        return fa_digits(f"{value:.1f}".replace(".", DECIMAL_SEP))
    return str(value)


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    """A finished, channel-agnostic message.

    ``action`` is a logical destination ("dashboard", "shop"), not a URL. The
    Telegram channel turns it into a callback button and the Mini App turns it
    into a route, so neither the domain nor the scheduler knows about either.
    """

    key: str
    category: NotificationCategory
    title_fa: str
    body_fa: str
    action: str | None = None

    def preview(self, limit: int = PREVIEW_LIMIT) -> str:
        """Short form for the Mini App inbox list and the admin log."""
        text = " ".join(self.body_fa.split())
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "\u2026"

    def telegram_text(self) -> str:
        """Telegram renders HTML; the title carries the weight."""
        return f"<b>{self.title_fa}</b>\n\n{self.body_fa}"

    def inbox_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "category": str(self.category),
            "title_fa": self.title_fa,
            "body_fa": self.body_fa,
            "preview_fa": self.preview(),
            "action": self.action,
        }


@dataclass(frozen=True, slots=True)
class MessageTemplate:
    """Persian copy plus the category that governs its delivery."""

    key: str
    category: NotificationCategory
    title_fa: str
    body_fa: str
    action: str | None = None

    def required_fields(self) -> frozenset[str]:
        formatter = string.Formatter()
        names = {name for _, name, _, _ in formatter.parse(self.title_fa + self.body_fa) if name}
        return frozenset(names)

    def render(self, **fields: Any) -> RenderedMessage:
        prepared: dict[str, str] = {}
        for name in self.required_fields():
            if name not in fields:
                raise MissingTemplateField(key=self.key, field=name)
            prepared[name] = _auto_format(fields[name])
        return RenderedMessage(
            key=self.key,
            category=self.category,
            title_fa=self.title_fa.format(**prepared),
            body_fa=self.body_fa.format(**prepared),
            action=self.action,
        )


_C = NotificationCategory

CATALOG: dict[str, MessageTemplate] = {
    t.key: t
    for t in (
        MessageTemplate(
            key="expiry.soon",
            category=_C.EXPIRY,
            title_fa="\u06cc\u0627\u062f\u0622\u0648\u0631\u06cc \u0627\u0646\u0642\u0636\u0627",
            body_fa=(
                "\u0627\u0634\u062a\u0631\u0627\u06a9 {plan} \u0634\u0645\u0627 "
                "{days} \u0631\u0648\u0632 \u062f\u06cc\u06af\u0631 "
                "\u0645\u0646\u0642\u0636\u06cc \u0645\u06cc\u200c\u0634\u0648\u062f. "
                "\u0628\u0631\u0627\u06cc \u062c\u0644\u0648\u06af\u06cc\u0631\u06cc "
                "\u0627\u0632 \u0642\u0637\u0639 \u0633\u0631\u0648\u06cc\u0633\u060c "
                "\u0647\u0645\u06cc\u0646 \u0627\u0644\u0627\u0646 "
                "\u062a\u0645\u062f\u06cc\u062f \u06a9\u0646\u06cc\u062f."
            ),
            action="dashboard",
        ),
        MessageTemplate(
            key="expiry.today",
            category=_C.EXPIRY,
            title_fa="\u0627\u0645\u0631\u0648\u0632 \u0622\u062e\u0631\u06cc\u0646 \u0631\u0648\u0632 \u0627\u0633\u062a",
            body_fa=(
                "\u0627\u0634\u062a\u0631\u0627\u06a9 {plan} \u0634\u0645\u0627 "
                "\u0627\u0645\u0631\u0648\u0632 \u0645\u0646\u0642\u0636\u06cc "
                "\u0645\u06cc\u200c\u0634\u0648\u062f."
            ),
            action="dashboard",
        ),
        MessageTemplate(
            key="expiry.expired",
            category=_C.CRITICAL,
            title_fa="\u0627\u0634\u062a\u0631\u0627\u06a9 \u0645\u0646\u0642\u0636\u06cc \u0634\u062f",
            body_fa=(
                "\u0627\u0634\u062a\u0631\u0627\u06a9 {plan} \u0634\u0645\u0627 "
                "\u0628\u0647 \u067e\u0627\u06cc\u0627\u0646 \u0631\u0633\u06cc\u062f "
                "\u0648 \u0627\u062a\u0635\u0627\u0644 \u0642\u0637\u0639 "
                "\u0634\u062f\u0647 \u0627\u0633\u062a."
            ),
            action="shop",
        ),
        MessageTemplate(
            key="traffic.warning",
            category=_C.TRAFFIC,
            title_fa="\u062d\u062c\u0645 \u0631\u0648 \u0628\u0647 \u067e\u0627\u06cc\u0627\u0646",
            body_fa=(
                "{percent} \u062f\u0631\u0635\u062f \u0627\u0632 "
                "\u062d\u062c\u0645 \u0628\u0633\u062a\u0647\u0654 {plan} "
                "\u0645\u0635\u0631\u0641 \u0634\u062f\u0647 \u0627\u0633\u062a. "
                "{remaining} \u0628\u0627\u0642\u06cc "
                "\u0645\u0627\u0646\u062f\u0647 \u0627\u0633\u062a."
            ),
            action="dashboard",
        ),
        MessageTemplate(
            key="traffic.exhausted",
            category=_C.CRITICAL,
            title_fa="\u062d\u062c\u0645 \u062a\u0645\u0627\u0645 \u0634\u062f",
            body_fa=(
                "\u062d\u062c\u0645 \u0628\u0633\u062a\u0647\u0654 {plan} "
                "\u062a\u0645\u0627\u0645 \u0634\u062f. \u0628\u0631\u0627\u06cc "
                "\u0627\u062f\u0627\u0645\u0647\u0654 \u0633\u0631\u0648\u06cc\u0633 "
                "\u0628\u0633\u062a\u0647\u0654 \u062c\u062f\u06cc\u062f "
                "\u062a\u0647\u06cc\u0647 \u06a9\u0646\u06cc\u062f."
            ),
            action="shop",
        ),
        MessageTemplate(
            key="wallet.credited",
            category=_C.CRITICAL,
            title_fa="\u06a9\u06cc\u0641 \u067e\u0648\u0644 \u0634\u0627\u0631\u0698 \u0634\u062f",
            body_fa=(
                "\u0645\u0628\u0644\u063a {amount} \u062a\u0648\u0645\u0627\u0646 "
                "\u0628\u0647 \u06a9\u06cc\u0641 \u067e\u0648\u0644 \u0634\u0645\u0627 "
                "\u0627\u0641\u0632\u0648\u062f\u0647 \u0634\u062f. "
                "\u0645\u0648\u062c\u0648\u062f\u06cc: {balance} "
                "\u062a\u0648\u0645\u0627\u0646."
            ),
            action="wallet",
        ),
        MessageTemplate(
            key="wallet.debited",
            category=_C.CRITICAL,
            title_fa="\u0628\u0631\u062f\u0627\u0634\u062a \u0627\u0632 \u06a9\u06cc\u0641 \u067e\u0648\u0644",
            body_fa=(
                "\u0645\u0628\u0644\u063a {amount} \u062a\u0648\u0645\u0627\u0646 "
                "\u0627\u0632 \u06a9\u06cc\u0641 \u067e\u0648\u0644 \u0634\u0645\u0627 "
                "\u06a9\u0633\u0631 \u0634\u062f. "
                "\u0645\u0648\u062c\u0648\u062f\u06cc: {balance} "
                "\u062a\u0648\u0645\u0627\u0646."
            ),
            action="wallet",
        ),
        MessageTemplate(
            key="payment.approved",
            category=_C.CRITICAL,
            title_fa="\u067e\u0631\u062f\u0627\u062e\u062a \u062a\u0623\u06cc\u06cc\u062f \u0634\u062f",
            body_fa=(
                "\u067e\u0631\u062f\u0627\u062e\u062a {amount} "
                "\u062a\u0648\u0645\u0627\u0646 \u0634\u0645\u0627 "
                "\u062a\u0623\u06cc\u06cc\u062f \u0634\u062f. "
                "\u06a9\u062f \u067e\u06cc\u06af\u06cc\u0631\u06cc: {reference}"
            ),
            action="dashboard",
        ),
        MessageTemplate(
            key="payment.rejected",
            category=_C.CRITICAL,
            title_fa="\u067e\u0631\u062f\u0627\u062e\u062a \u0631\u062f \u0634\u062f",
            body_fa=(
                "\u067e\u0631\u062f\u0627\u062e\u062a \u0628\u0627 "
                "\u06a9\u062f \u067e\u06cc\u06af\u06cc\u0631\u06cc {reference} "
                "\u062a\u0623\u06cc\u06cc\u062f \u0646\u0634\u062f. "
                "\u062f\u0644\u06cc\u0644: {reason}"
            ),
            action="support",
        ),
        MessageTemplate(
            key="payment.refunded",
            category=_C.CRITICAL,
            title_fa="\u0645\u0628\u0644\u063a \u0639\u0648\u062f\u062a \u062f\u0627\u062f\u0647 \u0634\u062f",
            body_fa=(
                "\u0645\u0628\u0644\u063a {amount} \u062a\u0648\u0645\u0627\u0646 "
                "\u0628\u0627\u0628\u062a \u06a9\u062f \u067e\u06cc\u06af\u06cc\u0631\u06cc "
                "{reference} \u0639\u0648\u062f\u062a \u062f\u0627\u062f\u0647 "
                "\u0634\u062f."
            ),
            action="wallet",
        ),
        MessageTemplate(
            key="purchase.completed",
            category=_C.CRITICAL,
            title_fa="\u062e\u0631\u06cc\u062f \u0645\u0648\u0641\u0642",
            body_fa=(
                "\u0628\u0633\u062a\u0647\u0654 {plan} \u0641\u0639\u0627\u0644 "
                "\u0634\u062f. \u0645\u062f\u062a: {days} \u0631\u0648\u0632 "
                "\u0648 \u062d\u062c\u0645: {volume}. "
                "\u0627\u0632 \u062e\u0631\u06cc\u062f \u0634\u0645\u0627 "
                "\u0633\u067e\u0627\u0633\u06af\u0632\u0627\u0631\u06cc\u0645."
            ),
            action="services",
        ),
        MessageTemplate(
            key="purchase.renewed",
            category=_C.CRITICAL,
            title_fa="\u0627\u0634\u062a\u0631\u0627\u06a9 \u062a\u0645\u062f\u06cc\u062f \u0634\u062f",
            body_fa=(
                "\u0627\u0634\u062a\u0631\u0627\u06a9 {plan} \u0628\u0647 "
                "\u0645\u062f\u062a {days} \u0631\u0648\u0632 \u062f\u06cc\u06af\u0631 "
                "\u062a\u0645\u062f\u06cc\u062f \u0634\u062f."
            ),
            action="services",
        ),
        MessageTemplate(
            key="referral.reward",
            category=_C.PROMOS,
            title_fa="\u0647\u062f\u06cc\u0647\u0654 \u0645\u0639\u0631\u0641\u06cc",
            body_fa=(
                "{amount} \u062a\u0648\u0645\u0627\u0646 \u0628\u0627\u0628\u062a "
                "\u0645\u0639\u0631\u0641\u06cc \u062f\u0648\u0633\u062a\u0627\u0646 "
                "\u0628\u0647 \u06a9\u06cc\u0641 \u067e\u0648\u0644 \u0634\u0645\u0627 "
                "\u0627\u0636\u0627\u0641\u0647 \u0634\u062f."
            ),
            action="referral",
        ),
        MessageTemplate(
            key="ticket.replied",
            category=_C.CRITICAL,
            title_fa="\u067e\u0627\u0633\u062e \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc",
            body_fa=(
                "\u0628\u0631\u0627\u06cc \u062a\u06cc\u06a9\u062a {reference} "
                "\u067e\u0627\u0633\u062e \u062c\u062f\u06cc\u062f\u06cc "
                "\u062b\u0628\u062a \u0634\u062f."
            ),
            action="support",
        ),
        MessageTemplate(
            key="ticket.closed",
            category=_C.CRITICAL,
            title_fa="\u062a\u06cc\u06a9\u062a \u0628\u0633\u062a\u0647 \u0634\u062f",
            body_fa=(
                "\u062a\u06cc\u06a9\u062a {reference} \u0628\u0633\u062a\u0647 "
                "\u0634\u062f. \u062f\u0631 \u0635\u0648\u0631\u062a "
                "\u0646\u06cc\u0627\u0632 \u062f\u0648\u0628\u0627\u0631\u0647 "
                "\u067e\u06cc\u0627\u0645 \u0628\u062f\u0647\u06cc\u062f."
            ),
            action="support",
        ),
        MessageTemplate(
            key="campaign.launched",
            category=_C.PROMOS,
            title_fa="{title}",
            body_fa=(
                "\u062a\u0627 {percent} \u062f\u0631\u0635\u062f "
                "\u062a\u062e\u0641\u06cc\u0641 \u0628\u0631\u0627\u06cc "
                "\u0645\u062f\u062a \u0645\u062d\u062f\u0648\u062f. "
                "\u0641\u0631\u0635\u062a \u0631\u0627 \u0627\u0632 "
                "\u062f\u0633\u062a \u0646\u062f\u0647\u06cc\u062f."
            ),
            action="shop",
        ),
        MessageTemplate(
            key="purchase.delivered",
            # CRITICAL: somebody paid, and this is the thing they paid for.
            # A preference that could silence it would silence the delivery,
            # not an announcement about it.
            category=_C.CRITICAL,
            title_fa="سرویس شما آماده است",
            body_fa=(
                "لینک اشتراک شما:\n\n"
                "<code>{link}</code>\n\n"
                "روی لینک بزنید تا کپی شود، بعد در برنامه‌ی خود واردش کنید."
            ),
            action="dashboard",
        ),
        MessageTemplate(
            key="purchase.delivered_no_link",
            # The account exists but its link has not been read back yet.
            # Saying so beats saying nothing: the customer can open "my
            # services" and the link will be there.
            category=_C.CRITICAL,
            title_fa="سرویس شما آماده است",
            body_fa=(
                "اکانت شما ساخته شد.\n\n"
                "لینک اتصال را از بخش «سرویس‌های من» بردارید."
            ),
            action="dashboard",
        ),
        MessageTemplate(
            key="ticket.answered",
            # Distinct from `ticket.replied`, which only says an answer exists.
            # A customer told "there is a reply, go and look" has to leave the
            # chat to read three lines, and most of them do not - so the answer
            # travels with the notice, and replying to this message answers
            # back. The reference is in the text because that is what the reply
            # handler reads to know which ticket this is.
            category=_C.CRITICAL,
            title_fa="پاسخ پشتیبانی",
            body_fa=(
                "تیکت {reference}\n\n"
                "{body}\n\n"
                "برای ادامه‌ی گفتگو، روی همین پیام ریپلای کنید و پاسخ‌تان را بنویسید."
            ),
            action="support",
        ),
        MessageTemplate(
            key="payment.receipt_requested",
            # CRITICAL, because the customer asked for it seconds ago and is
            # waiting on it. Any other category can be switched off in their
            # own settings, and a prompt that never arrives leaves them holding
            # a receipt for a transfer nobody knows about.
            category=_C.CRITICAL,
            title_fa="رسید پرداخت",
            body_fa=(
                "عکس رسید واریز {amount} تومان را همین‌جا بفرستید.\n\n"
                "به همان پرداخت وصل می‌شود و بررسی‌اش را شروع می‌کنیم."
            ),
            action=None,
        ),
        MessageTemplate(
            key="broadcast.custom",
            category=_C.NEWS,
            title_fa="{title}",
            body_fa="{body}",
            action=None,
        ),
    )
}


def render(key: str, **fields: Any) -> RenderedMessage:
    """Render a catalogue template, or fail loudly for an unknown key."""
    template = CATALOG.get(key)
    if template is None:
        raise TemplateNotFound(key)
    return template.render(**fields)


def template_keys() -> tuple[str, ...]:
    return tuple(sorted(CATALOG))


__all__ = [
    "CATALOG",
    "DECIMAL_SEP",
    "GIB",
    "PERSIAN_DIGITS",
    "PREVIEW_LIMIT",
    "THOUSANDS_SEP",
    "TOMAN",
    "UNLIMITED",
    "MessageTemplate",
    "RenderedMessage",
    "fa_digits",
    "fa_gib",
    "fa_number",
    "fa_toman",
    "render",
    "template_keys",
]
