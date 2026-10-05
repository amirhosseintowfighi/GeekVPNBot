"""The SQL behind auto-renewal, transfers and giving a coupon back.

Logic is covered by unit tests; these pin the parts that are queries: which
rows the renewal sweep picks, that a transfer's new owner is actually written
(the mapper never wrote `user_id` back, because nothing changed it before),
and that a released coupon use really leaves the table.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from geekvpn.domain.provisioning.enums import SubscriptionState
from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.persistence.base import Base
from geekvpn.infrastructure.persistence.models.catalog import (
    CouponModel,
    CouponRedemptionModel,
)
from geekvpn.infrastructure.persistence.models.identity import UserModel
from geekvpn.infrastructure.persistence.models.provisioning import SubscriptionModel
from geekvpn.infrastructure.persistence.repositories.provisioning import (
    SqlAlchemySubscriptionRepository,
)
from geekvpn.infrastructure.persistence.repositories.sync_catalog import SyncCouponReleaser

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


@pytest.fixture
def schema() -> Iterator[None]:
    engine = create_engine(
        get_settings().postgres.dsn(driver="postgresql+psycopg"), pool_pre_ping=True
    )
    try:
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"no Postgres available: {exc.__class__.__name__}")
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture
async def session(schema: None) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().postgres.dsn())
    async with async_sessionmaker(engine, expire_on_commit=False)() as opened:
        yield opened
    await engine.dispose()


def subscription(
    sub_id: str, *, auto_renew: bool, expires_in: timedelta, state: str = "active"
) -> SubscriptionModel:
    return SubscriptionModel(
        id=sub_id,
        user_id=1001,
        state=state,
        remote_username=f"gv_{sub_id}",
        started_at=NOW - timedelta(days=30),
        expires_at=NOW + expires_in,
        traffic_used_mib=0,
        device_limit=1,
        notified_expiry_days=[],
        notified_traffic_percents=[],
        auto_renew=auto_renew,
    )


async def test_the_sweep_picks_only_opted_in_active_services_ending_soon(
    session: AsyncSession,
) -> None:
    session.add_all(
        [
            subscription("due", auto_renew=True, expires_in=timedelta(hours=5)),
            subscription("not_opted", auto_renew=False, expires_in=timedelta(hours=5)),
            subscription("later", auto_renew=True, expires_in=timedelta(days=5)),
            subscription(
                "suspended",
                auto_renew=True,
                expires_in=timedelta(hours=5),
                state=SubscriptionState.SUSPENDED.value,
            ),
        ]
    )
    await session.commit()

    due = await SqlAlchemySubscriptionRepository(session).list_auto_renew_due(
        before=NOW + timedelta(hours=24)
    )

    assert [s.id for s in due] == ["due"]


async def test_a_transfer_writes_the_new_owner(session: AsyncSession) -> None:
    session.add(subscription("gift", auto_renew=True, expires_in=timedelta(days=10)))
    await session.commit()
    repo = SqlAlchemySubscriptionRepository(session)

    sub = await repo.get("gift")
    assert sub is not None
    sub.transfer_to(2002)
    sub.rename("گوشی مامان")
    await repo.update(sub)
    await session.commit()
    session.expire_all()

    stored = await repo.get("gift")
    assert stored is not None
    assert (stored.user_id, stored.auto_renew, stored.display_name) == (2002, False, "گوشی مامان")


def test_releasing_a_coupon_deletes_the_orders_use_and_counts_it_back(schema: None) -> None:
    engine = create_engine(get_settings().postgres.dsn(driver="postgresql+psycopg"))
    order_id = uuid.uuid4()
    with Session(engine) as db:
        user = UserModel(
            id=uuid.uuid4(), telegram_id=1001, status="active", referral_code="r1", language="fa"
        )
        coupon = CouponModel(
            id=uuid.uuid4(),
            code="SPRING",
            kind="public",
            discount_kind="percentage",
            discount_value=10,
            max_per_user=1,
            redemption_count=1,
            state="published",
        )
        db.add_all([user, coupon])
        db.flush()
        db.add(
            CouponRedemptionModel(
                id=uuid.uuid4(),
                coupon_id=coupon.id,
                user_id=user.id,
                order_id=order_id,
                discount=5_000,
                redeemed_at=NOW,
            )
        )
        db.commit()

        SyncCouponReleaser(db).release(code="spring", order_id=order_id.hex)
        db.commit()

        assert db.execute(select(CouponRedemptionModel)).first() is None
        assert db.get(CouponModel, coupon.id).redemption_count == 0  # type: ignore[union-attr]
    engine.dispose()


async def test_the_daily_cap_counts_only_new_services_that_went_ahead(
    session: AsyncSession,
) -> None:
    from geekvpn.infrastructure.persistence.models.provisioning import OrderModel
    from geekvpn.infrastructure.persistence.repositories.provisioning import (
        SqlAlchemyOrderRepository,
    )

    def order(
        number: str,
        *,
        state: str = "paid",
        renewal: bool = False,
        source: str = "bot",
        hours_ago: int = 1,
    ) -> OrderModel:
        return OrderModel(
            id=uuid.uuid4().hex,
            number=number,
            user_id=1001,
            state=state,
            plan_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            plan_name_fa="ماهانه",
            duration_days=30,
            list_price=100_000,
            total=100_000,
            is_renewal=renewal,
            source=source,
            placed_at=NOW - timedelta(hours=hours_ago),
        )

    session.add_all(
        [
            order("A-1"),
            order("A-2", state="pending"),
            order("A-3", renewal=True),
            order("A-4", state="cancelled"),
            order("A-5", source="trial"),
            order("A-6", hours_ago=30),
        ]
    )
    await session.commit()

    counted = await SqlAlchemyOrderRepository(session).count_new_purchases_since(
        1001, NOW - timedelta(hours=12)
    )

    assert counted == 2


async def test_the_cleanup_picks_only_long_dead_services(session: AsyncSession) -> None:
    session.add_all(
        [
            subscription("old", auto_renew=False, expires_in=-timedelta(days=5), state="expired"),
            subscription(
                "fresh", auto_renew=False, expires_in=-timedelta(hours=1), state="expired"
            ),
            subscription("live", auto_renew=False, expires_in=timedelta(days=5)),
            subscription(
                "banned", auto_renew=False, expires_in=-timedelta(days=5), state="suspended"
            ),
        ]
    )
    await session.commit()

    due = await SqlAlchemySubscriptionRepository(session).list_lapsed_before(
        cutoff=NOW - timedelta(days=2)
    )

    assert [s.id for s in due] == ["old"]
