"""Message body composition.

Renderers are pure: read models in, string out. No I/O, no aiogram types.
That makes the entire visual surface of the bot unit-testable without a
Telegram client, which is how we can assert RTL correctness in CI.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from geekvpn.application.bot.read_models import (
    NotificationPreferences,
    ProfileSummary,
    ReferralSummary,
    ServerHealth,
    ServerStatusRow,
    SubscriptionCard,
    SubscriptionState,
    TicketCard,
    TicketMessageCard,
    TicketState,
    TransactionKind,
    WalletSnapshot,
    WalletTransaction,
)
from geekvpn.application.catalog.dto import PlanView, ProductView, QuoteView
from geekvpn.presentation.bot.ui import emoji as E
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.fa import (
    countdown,
    fa_date,
    fa_datetime,
    fa_digits,
    fa_duration,
    fa_relative,
    gib,
    isolate,
    percent,
    progress_bar,
    ratio,
    rtl_line,
    toman,
    truncate,
)

SEPARATOR = "\u2014" * 12

_STATE_LABEL = {
    SubscriptionState.PENDING: (E.PENDING, T.SUB_PENDING),
    SubscriptionState.ACTIVE: (E.ACTIVE, T.SUB_ACTIVE),
    SubscriptionState.EXPIRING: (E.EXPIRING, T.SUB_EXPIRING),
    SubscriptionState.EXPIRED: (E.EXPIRED, T.SUB_EXPIRED),
    SubscriptionState.EXHAUSTED: (E.EXPIRED, T.SUB_EXHAUSTED),
    SubscriptionState.SUSPENDED: (E.WARN, T.SUB_SUSPENDED),
}

_HEALTH_LABEL = {
    ServerHealth.HEALTHY: (E.ACTIVE, T.STATUS_OPERATIONAL),
    ServerHealth.DEGRADED: (E.DEGRADED, T.STATUS_DEGRADED),
    ServerHealth.DOWN: (E.EXPIRED, T.STATUS_DOWN),
    ServerHealth.MAINTENANCE: (E.PENDING, T.STATUS_MAINTENANCE),
}

_TXN_LABEL = {
    TransactionKind.TOPUP: T.TXN_TOPUP,
    TransactionKind.PURCHASE: T.TXN_PURCHASE,
    TransactionKind.CASHBACK: T.TXN_CASHBACK,
    TransactionKind.REFERRAL: T.TXN_REFERRAL,
    TransactionKind.REFUND: T.TXN_REFUND,
    TransactionKind.ADJUSTMENT: T.TXN_ADJUSTMENT,
}

_TICKET_LABEL = {
    TicketState.OPEN: T.TICKET_OPEN,
    TicketState.ANSWERED: T.TICKET_ANSWERED,
    TicketState.CLOSED: T.TICKET_CLOSED,
}


def greeting(name: str, *, hour: int) -> str:
    """Time-of-day greeting. `hour` is already in the user's local timezone."""
    if 5 <= hour < 12:
        template = T.GREETING_MORNING
    elif 12 <= hour < 17:
        template = T.GREETING_DAY
    elif 17 <= hour < 21:
        template = T.GREETING_EVENING
    else:
        template = T.GREETING_NIGHT
    return template.format(name=isolate(name))


def home(
    *,
    name: str,
    hour: int,
    balance: int,
    tier_label: str,
    tier_emoji: str,
    active_count: int,
) -> str:
    active = (
        f"{fa_digits(active_count)} \u0633\u0631\u0648\u06cc\u0633"
        if active_count
        else "\u0646\u062f\u0627\u0631\u06cc\u062f"
    )
    return T.HOME_BODY.format(
        greeting=greeting(name, hour=hour),
        balance=toman(balance),
        tier=tier_label,
        tier_emoji=tier_emoji,
        active=active,
    )


# -- Storefront --------------------------------------------------------------


def product_card(product: ProductView) -> str:
    """Full product page: pitch, features, then the package list."""
    lines: list[str] = []
    icon = product.icon or E.ROCKET
    lines.append(rtl_line(f"{icon} <b>{product.name}</b>"))
    if product.badge:
        lines.append(rtl_line(f"{E.DISCOUNT} {product.badge}"))
    if product.tagline:
        lines.append("")
        lines.append(rtl_line(f"<i>{product.tagline}</i>"))
    if product.description:
        lines.append("")
        lines.append(rtl_line(product.description))
    if product.features:
        lines.append("")
        for feature in product.features:
            lines.append(rtl_line(f"{E.OK} {feature}"))
    cheapest = product.cheapest_price
    if cheapest is not None:
        lines.append("")
        lines.append(rtl_line(T.PLAN_FROM.format(price=f"<b>{toman(cheapest)}</b>")))
    lines.append("")
    lines.append(rtl_line(T.PRODUCT_PICK_PLAN))
    return "\n".join(lines)


def plan_button_label(plan: PlanView) -> str:
    """Compact one-line label for a package button.

    Shows the discounted price when there is one; the strike-through original
    goes in the detail view, because a button is not the place for two prices.
    """
    quota = gib(plan.quota_gib)
    duration = fa_duration(plan.duration_days)
    price = plan.price.total
    label = f"{quota} \u00b7 {duration} \u00b7 {toman(price)}"
    if plan.price.campaign_label:
        label = f"{E.FIRE} {label}"
    elif plan.is_featured:
        label = f"\u2b50 {label}"
    return label


def quote_breakdown(quote: QuoteView, *, plan_name: str, compact: bool = False) -> str:
    """Itemised price breakdown.

    Every deduction is shown as its own line with a `−` sign, and cashback is
    rendered *below* the total with a `+`, never subtracted from it. A
    customer must never be able to read the invoice as cheaper than what will
    actually leave their wallet.
    """
    lines: list[str] = []
    if not compact:
        # `REVIEW_TITLE` carries its own receipt emoji; prefixing another one
        # printed it twice.
        lines.append(rtl_line(f"<b>{T.REVIEW_TITLE}</b>"))
        lines.append("")
        lines.append(rtl_line(f"{E.CART} {plan_name}"))
        lines.append("")

    for line in quote.lines:
        if line.kind == "base":
            lines.append(rtl_line(f"{T.LBL_PRICE}: {toman(line.amount)}"))
        elif line.is_deduction:
            lines.append(rtl_line(f"{E.DISCOUNT} {line.label}: \u2212{toman(line.amount)}"))

    lines.append("")
    lines.append(rtl_line(f"<b>{T.LBL_TOTAL}: {toman(quote.total)}</b>"))

    if quote.discount_percent > 0:
        saved = quote.base_price - quote.total
        lines.append(
            rtl_line(
                f"{E.SPARKLE} \u0634\u0645\u0627 {toman(saved)} "
                f"({percent(quote.discount_percent)}) \u0635\u0631\u0641\u0647\u200c\u062c\u0648\u06cc\u06cc \u06a9\u0631\u062f\u06cc\u062f"
            )
        )
    if quote.cashback:
        lines.append(rtl_line(f"{E.CASHBACK} {T.LBL_CASHBACK}: +{toman(quote.cashback)}"))
    if quote.flash_sale_ends_in:
        lines.append("")
        lines.append(
            rtl_line(T.FLASH_ENDS_IN.format(remaining=countdown(quote.flash_sale_ends_in)))
        )
    return "\n".join(lines)


def plan_detail(
    plan: PlanView,
    *,
    product_name: str,
    quote: QuoteView | None = None,
    features: Sequence[str] = (),
) -> str:
    """The screen a customer reads before pressing pay.

    It used to be a price breakdown and nothing else: a customer who tapped a
    package saw a total, a discount and a cashback line, and not one word about
    what they were buying - no volume, no duration, no device count, none of
    the features the operator had written on the product. Those facts existed
    and were rendered by this function, which nothing called.

    `quote` overrides the plan's own price because the review screen re-quotes
    with a coupon applied; without it the customer would read the pre-coupon
    total on the screen where they confirm the discounted one.
    """
    lines: list[str] = [rtl_line(f"{E.CART} <b>{product_name}</b> \u2014 {plan.name}")]
    if plan.badge:
        lines.append(rtl_line(f"{E.DISCOUNT} {plan.badge}"))
    if plan.description:
        lines.append("")
        lines.append(rtl_line(f"<i>{plan.description}</i>"))

    lines.append("")
    lines.append(rtl_line(f"{E.CALENDAR} {T.LBL_DURATION}: <b>{fa_duration(plan.duration_days)}</b>"))
    lines.append(rtl_line(f"{E.CHART} {T.LBL_TRAFFIC}: <b>{gib(plan.quota_gib)}</b>"))
    lines.append(rtl_line(f"{E.DEVICE} {T.LBL_DEVICES}: <b>{fa_digits(plan.device_limit)}</b>"))

    # The product's selling points, on the screen where they are being sold.
    # They were only ever shown one step earlier, on the page listing the
    # packages, and vanished the moment the customer picked one.
    for feature in features:
        lines.append(rtl_line(f"{E.OK} {feature}"))

    lines.append("")
    # Compact: the header two lines up already names the package, and a
    # heading reading "order review" above a screen titled with the package is
    # one label too many.
    lines.append(quote_breakdown(quote or plan.price, plan_name=plan.name, compact=True))
    lines.append("")
    lines.extend(rtl_line(line) for line in T.PLAN_TRUST.split("\n"))
    return "\n".join(lines)


# -- Dashboard ---------------------------------------------------------------


def subscription_button_label(card: SubscriptionCard) -> str:
    state_emoji, _ = _STATE_LABEL.get(card.state, (E.INFO, ""))
    return f"{state_emoji} {card.product_name_fa} \u00b7 {card.plan_name_fa}"


def subscription_detail(card: SubscriptionCard, *, now: datetime) -> str:
    state_emoji, state_label = _STATE_LABEL.get(card.state, (E.INFO, T.STATUS_UNKNOWN))

    if card.expires_at is None:
        expires = "\u2014"
        remaining = "\u2014"
    else:
        expires = fa_date(card.expires_at)
        remaining = fa_relative(card.expires_at - now)

    if card.is_unlimited:
        used = f"{gib(card.used_gib)} \u0627\u0632 \u0646\u0627\u0645\u062d\u062f\u0648\u062f"
        bar = progress_bar(0.0)
    else:
        used = ratio(card.used_gib, card.quota_gib)
        bar = progress_bar(card.usage_fraction)

    # Nothing records how many devices are connected right now - that would be a
    # live panel query - so the plan's allowance is the only honest number here.
    devices = fa_digits(card.device_limit)

    return T.SUB_DETAIL.format(
        icon=E.ROCKET,
        name=f"<b>{card.product_name_fa}</b> \u2014 {card.plan_name_fa}",
        status_emoji=state_emoji,
        status=state_label,
        expires=expires,
        remaining=remaining,
        bar=bar,
        used=used,
        devices=devices,
    )


# -- Wallet ------------------------------------------------------------------


def wallet(
    snapshot: WalletSnapshot,
    *,
    tier_label: str,
    tier_emoji: str,
    cashback_percent: float = 0.0,
) -> str:
    pending_line = (
        T.WALLET_PENDING_LINE.format(amount=toman(snapshot.pending_credit))
        if snapshot.pending_credit
        else ""
    )
    return T.WALLET_BODY.format(
        balance=f"<b>{toman(snapshot.balance)}</b>",
        pending_line=pending_line,
        tier=tier_label,
        tier_emoji=tier_emoji,
        cashback_rate=percent(cashback_percent),
    )


def wallet_history(transactions: list[WalletTransaction]) -> str:
    if not transactions:
        return rtl_line(T.WALLET_HISTORY_EMPTY)
    lines = [rtl_line(f"<b>{T.WALLET_HISTORY_TITLE}</b>"), ""]
    for txn in transactions:
        label = _TXN_LABEL.get(txn.kind, T.TXN_ADJUSTMENT)
        sign = "+" if txn.is_credit else "\u2212"
        mark = E.OK if txn.is_credit else E.CARD
        lines.append(rtl_line(f"{mark} {label}"))
        lines.append(
            rtl_line(f"    {sign}{toman(abs(txn.amount))} \u00b7 {fa_date(txn.created_at)}")
        )
    return "\n".join(lines)


# -- Referral ----------------------------------------------------------------


def referral(
    summary: ReferralSummary,
    *,
    link: str,
    invitee_bonus: int,
    first_rate_bps: int,
    recurring_rate_bps: int,
) -> str:
    body = T.REF_BODY.format(
        invitee_bonus=toman(invitee_bonus),
        first_rate=percent(first_rate_bps / 100),
        recurring_rate=percent(recurring_rate_bps / 100),
        count=fa_digits(summary.converted_count),
        earned=toman(summary.total_earned),
    )
    # The link is Latin and must not be reordered by the surrounding Persian.
    return f"{body}\n\n<code>{link}</code>"


def referral_share_text(link: str) -> str:
    return f"{T.REF_SHARE_TEXT}\n{link}"


# -- Profile -----------------------------------------------------------------


def profile(
    summary: ProfileSummary,
    *,
    tier_label: str,
    tier_emoji: str,
    balance: int,
) -> str:
    return T.PROFILE_BODY.format(
        name=isolate(summary.display_name),
        code=f"<code>{summary.referral_code}</code>",
        tier=tier_label,
        tier_emoji=tier_emoji,
        joined=fa_date(summary.joined_at) if summary.joined_at else "—",
        orders=fa_digits(summary.order_count),
        balance=toman(balance),
    )


def tier_progress(*, spend: int, next_threshold: int | None, next_tier_label: str | None) -> str:
    if next_threshold is None or next_tier_label is None:
        return rtl_line(T.PROFILE_TIER_MAX)
    remaining = max(0, next_threshold - spend)
    fraction = 1.0 if next_threshold <= 0 else min(1.0, spend / next_threshold)
    return T.PROFILE_TIER_PROGRESS.format(
        bar=progress_bar(fraction),
        next_tier=next_tier_label,
        remaining=toman(remaining),
    )


# -- Settings ----------------------------------------------------------------


def settings_body(preferences: NotificationPreferences) -> str:
    lines = [rtl_line(f"<b>{T.SETTINGS_TITLE}</b>"), "", rtl_line(T.SETTINGS_INTRO)]
    if preferences.quiet_hours:
        lines.append("")
        lines.append(rtl_line(f"{E.INFO} {T.SETTINGS_QUIET_HINT}"))
    return "\n".join(lines)


# -- Server status -----------------------------------------------------------


def server_status(rows: list[ServerStatusRow], *, checked_at: datetime) -> str:
    if not rows:
        return rtl_line(T.STATUS_NO_SERVERS)

    all_ok = all(r.health is ServerHealth.HEALTHY for r in rows)
    header = T.STATUS_ALL_OK if all_ok else T.STATUS_SOME_DEGRADED

    lines = [rtl_line(f"<b>{T.STATUS_TITLE}</b>"), "", rtl_line(header), ""]
    for row in rows:
        mark, label = _HEALTH_LABEL.get(row.health, (E.INFO, T.STATUS_UNKNOWN))
        line = f"{mark} {row.flag} {row.name_fa} \u2014 {label}"
        if row.load_percent is not None and row.health is not ServerHealth.DOWN:
            line += f" ({T.STATUS_LOAD} {percent(row.load_percent)})"
        lines.append(rtl_line(line))
    lines.append("")
    lines.append(rtl_line(T.STATUS_UPDATED_AT.format(at=fa_datetime(checked_at))))
    return "\n".join(lines)


# -- Support -----------------------------------------------------------------


def ticket_button_label(ticket: TicketCard) -> str:
    state = _TICKET_LABEL.get(ticket.state, "")
    badge = f" ({fa_digits(ticket.unread_count)})" if ticket.unread_count else ""
    return f"{state} {ticket.topic_fa}{badge}"


#: How much of a thread fits in one Telegram message. The tail is the part
#: anyone is reading; the whole conversation stays in the Mini App.
THREAD_MESSAGES = 6
THREAD_BODY_CHARS = 400


def ticket_thread(card: TicketCard, messages: list[TicketMessageCard]) -> str:
    """One ticket, as a conversation.

    Newest last, the way a chat reads. Trimmed to the tail because a Telegram
    message has a hard length limit and the useful end of a support thread is
    always the recent one - the whole of it stays in the Mini App.
    """
    header = T.TICKET_THREAD_HEADER.format(
        topic=card.topic_fa,
        ref=card.reference,
        state=_TICKET_LABEL.get(card.state, ""),
    )
    if not messages:
        return rtl_line(header) + "\n\n" + rtl_line(T.TICKET_THREAD_EMPTY)

    lines = [rtl_line(header), ""]
    for message in messages[-THREAD_MESSAGES:]:
        side = T.TICKET_SIDE_SUPPORT if message.from_support else T.TICKET_SIDE_CUSTOMER
        lines.append(rtl_line(f"<b>{side}</b> · {fa_date(message.created_at)}"))
        lines.append(rtl_line(truncate(message.body_fa, THREAD_BODY_CHARS)))
        lines.append("")
    return "\n".join(lines).rstrip()


def ticket_list(tickets: list[TicketCard]) -> str:
    if not tickets:
        return rtl_line(T.TICKET_LIST_EMPTY)
    lines = [rtl_line(f"<b>{T.BTN_MY_TICKETS}</b>"), ""]
    for ticket in tickets:
        state = _TICKET_LABEL.get(ticket.state, "")
        lines.append(rtl_line(f"{state} {ticket.topic_fa}"))
        lines.append(
            rtl_line(f"    <code>{ticket.reference}</code> \u00b7 {fa_date(ticket.created_at)}")
        )
    return "\n".join(lines)
