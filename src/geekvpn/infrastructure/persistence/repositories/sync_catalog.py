"""The corner of the catalog the payment scope has to write to.

Coupon uses are counted in the async scope when an order is placed, but the
payment that decides whether that order ever happens is rejected, failed or
expired in the synchronous one. Giving the use back belongs in that same
transaction, so it is a sync writer rather than a hop back into the async
repository. See `sync_scope.py` for why the two sides exist at all.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from geekvpn.domain.catalog.coupon import normalise_code
from geekvpn.infrastructure.persistence.models.catalog import (
    CouponModel,
    CouponRedemptionModel,
)


class SyncCouponReleaser:
    """``application.provisioning.ports.CouponReleaser``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def release(self, *, code: str, order_id: str) -> None:
        coupon_id = self._session.execute(
            CouponModel.__table__.select()
            .with_only_columns(CouponModel.id)
            .where(CouponModel.code == normalise_code(code))
        ).scalar_one_or_none()
        if coupon_id is None:
            # Archived or deleted since the order was placed: nothing to give back.
            return

        order_uuid = _as_uuid(order_id)
        if order_uuid is not None:
            self._session.execute(
                delete(CouponRedemptionModel).where(
                    CouponRedemptionModel.coupon_id == coupon_id,
                    CouponRedemptionModel.order_id == order_uuid,
                )
            )
        # Floored at zero rather than trusted: the counter predates the
        # per-order rows, and a check constraint violation here would roll back
        # the payment rejection that called us.
        self._session.execute(
            update(CouponModel)
            .where(CouponModel.id == coupon_id, CouponModel.redemption_count > 0)
            .values(redemption_count=CouponModel.redemption_count - 1)
        )
        self._session.flush()


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


__all__ = ["SyncCouponReleaser"]
