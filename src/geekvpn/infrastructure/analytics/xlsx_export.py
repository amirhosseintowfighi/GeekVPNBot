"""Orders and customers as an Excel workbook, for the operator to take away.

Built from SQL rather than through the repositories: an export is every row,
and loading each one into an aggregate to read three fields back out of it
would turn a few seconds into minutes on a shop with a real customer base.

Dates are written twice, as the Jalali date an operator reads and as the UTC
timestamp a spreadsheet can sort and filter. One without the other is either
unreadable or unsortable.
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from geekvpn.domain.analytics.calendar import to_jalali
from geekvpn.infrastructure.persistence.models.identity import UserModel
from geekvpn.infrastructure.persistence.models.payments import WalletEntryModel
from geekvpn.infrastructure.persistence.models.provisioning import (
    OrderModel,
    SubscriptionModel,
)

TEHRAN = timezone(timedelta(hours=3, minutes=30))

#: Order states that represent money actually taken, as the audiences read it.
PAID_STATES = ("paid", "provisioning", "active")

ORDER_COLUMNS = (
    "شماره سفارش",
    "آیدی عددی کاربر",
    "پلن",
    "مبلغ کل (تومان)",
    "تخفیف (تومان)",
    "کد تخفیف",
    "وضعیت",
    "تمدید",
    "منبع",
    "تاریخ ثبت",
    "زمان ثبت (UTC)",
)
CUSTOMER_COLUMNS = (
    "آیدی عددی",
    "یوزرنیم",
    "نام",
    "وضعیت",
    "موجودی کیف پول (تومان)",
    "تعداد خرید موفق",
    "جمع خرید (تومان)",
    "سرویس فعال",
    "تاریخ عضویت",
    "آخرین فعالیت",
)


def _jalali(value: datetime | None) -> str:
    if value is None:
        return ""
    local = value.astimezone(TEHRAN)
    year, month, day = to_jalali(local.date())
    return f"{year}/{month:02d}/{day:02d} {local:%H:%M}"


def _utc(value: datetime | None) -> datetime | None:
    # openpyxl refuses aware datetimes; the column header says it is UTC.
    return value.astimezone(UTC).replace(tzinfo=None) if value else None


def _sheet(book: Workbook, title: str, header: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    sheet: Worksheet = book.create_sheet(title)
    sheet.sheet_view.rightToLeft = True
    sheet.append(list(header))
    for row in rows:
        sheet.append(list(row))
    sheet.freeze_panes = "A2"
    for index, column in enumerate(sheet.columns, start=1):
        width = max(len(str(cell.value or "")) for cell in column)
        sheet.column_dimensions[get_column_letter(index)].width = min(max(width + 2, 10), 40)


def order_rows(session: Session) -> list[tuple[Any, ...]]:
    orders = session.execute(select(OrderModel).order_by(OrderModel.placed_at.desc())).scalars()
    return [
        (
            order.number,
            order.user_id,
            order.plan_name_fa,
            order.total,
            order.discount,
            order.coupon_code or "",
            order.state,
            "بله" if order.is_renewal else "",
            order.source,
            _jalali(order.placed_at),
            _utc(order.placed_at),
        )
        for order in orders
    ]


def customer_rows(session: Session, *, now: datetime) -> list[tuple[Any, ...]]:
    balance = (
        select(
            WalletEntryModel.user_id.label("user_id"),
            WalletEntryModel.reseller_id.label("reseller_id"),
            func.sum(WalletEntryModel.amount).label("balance"),
        )
        .group_by(WalletEntryModel.user_id, WalletEntryModel.reseller_id)
        .subquery()
    )
    spent = (
        select(
            OrderModel.user_id.label("user_id"),
            OrderModel.reseller_id.label("reseller_id"),
            func.count().label("orders"),
            func.sum(OrderModel.total).label("total"),
        )
        .where(OrderModel.state.in_(PAID_STATES))
        .group_by(OrderModel.user_id, OrderModel.reseller_id)
        .subquery()
    )
    live = (
        select(SubscriptionModel.user_id.label("user_id"), func.count().label("live"))
        .where(SubscriptionModel.state == "active", SubscriptionModel.expires_at > now)
        .group_by(SubscriptionModel.user_id)
        .subquery()
    )
    # Matched on the shop as well as the Telegram id: the same person in two
    # shops is two customers with two wallets.
    same_shop_balance = balance.c.reseller_id.is_not_distinct_from(UserModel.reseller_id)
    same_shop_orders = spent.c.reseller_id.is_not_distinct_from(UserModel.reseller_id)
    statement = (
        select(
            UserModel,
            func.coalesce(balance.c.balance, 0),
            func.coalesce(spent.c.orders, 0),
            func.coalesce(spent.c.total, 0),
            func.coalesce(live.c.live, 0),
        )
        .outerjoin(
            balance, (balance.c.user_id == UserModel.telegram_id) & same_shop_balance
        )
        .outerjoin(spent, (spent.c.user_id == UserModel.telegram_id) & same_shop_orders)
        .outerjoin(live, live.c.user_id == UserModel.telegram_id)
        .order_by(UserModel.created_at)
    )
    rows: list[tuple[Any, ...]] = []
    for user, wallet, orders, total, services in session.execute(statement).all():
        name = " ".join(part for part in (user.first_name, user.last_name) if part)
        rows.append(
            (
                user.telegram_id,
                f"@{user.username}" if user.username else "",
                user.preferred_name or name,
                user.status,
                int(wallet),
                int(orders),
                int(total),
                int(services),
                _jalali(user.created_at),
                _jalali(user.last_seen_at),
            )
        )
    return rows


def build_workbook(session: Session, *, now: datetime) -> bytes:
    """Both sheets in one file, as the bytes Telegram uploads."""
    book = Workbook()
    # The default empty sheet would be the first tab the operator sees.
    book.remove(book.active)  # type: ignore[arg-type]
    _sheet(book, "سفارش‌ها", ORDER_COLUMNS, order_rows(session))
    _sheet(book, "کاربران", CUSTOMER_COLUMNS, customer_rows(session, now=now))
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


__all__ = ["CUSTOMER_COLUMNS", "ORDER_COLUMNS", "build_workbook", "customer_rows", "order_rows"]
