"""Coupons: discounts the customer has to type in.

Every redemption rule is checked in the aggregate, and each failure mode raises
a *distinct* error. "Invalid code" is the single least helpful message in
e-commerce - it turns a customer who mistyped, a customer whose code expired
yesterday, and a customer using a code meant for someone else into three
identical support tickets.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Final

from geekvpn.domain.base.entity import AggregateRoot
from geekvpn.domain.catalog.discount import Discount
from geekvpn.domain.catalog.enums import CouponKind, PublicationState
from geekvpn.domain.catalog.errors import (
    CatalogValidationError,
    CouponExhausted,
    CouponExpired,
    CouponNotApplicable,
)
from geekvpn.domain.catalog.events import CouponRedeemed
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.scope import PromotionScope, PromotionTarget
from geekvpn.domain.catalog.window import TimeWindow

CODE_PATTERN: Final = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,31}$")


#: Persian (U+06F0..) and Arabic-Indic (U+0660..) digits folded to ASCII.
DIGIT_FOLD: Final = str.maketrans(
    {
        **{chr(0x06F0 + n): str(n) for n in range(10)},
        **{chr(0x0660 + n): str(n) for n in range(10)},
    }
)


def normalise_code(raw: str) -> str:
    """Uppercase, strip, and fold non-ASCII digits.

    Customers paste codes out of Telegram messages with stray spaces and in
    whatever case they feel like. Normalising at the boundary means the unique
    index does the deduplication and `GEEK50` never coexists with `geek50`.

    A customer on a Persian keyboard types WELCOME۱۰, not WELCOME10. Those are
    the same code to a human, so rejecting the Persian form would turn every
    numeric coupon into a support ticket.
    """
    code = (raw or "").strip().translate(DIGIT_FOLD).upper().replace(" ", "")
    if not CODE_PATTERN.match(code):
        raise CatalogValidationError(
            "A coupon code must be 3-32 characters of A-Z, 0-9 and hyphens.",
            code=code,
        )
    return code


class Coupon(AggregateRoot[uuid.UUID]):
    """A redeemable discount code."""

    __slots__ = (
        "code",
        "created_at",
        "created_by",
        "description_fa",
        "discount",
        "first_purchase_only",
        "kind",
        "max_per_user",
        "max_redemptions",
        "min_order_amount",
        "redemption_count",
        "scope",
        "stacks_with_campaign",
        "state",
        "target_user_id",
        "window",
    )

    def __init__(
        self,
        *,
        coupon_id: uuid.UUID,
        code: str,
        kind: CouponKind,
        discount: Discount,
        window: TimeWindow | None = None,
        scope: PromotionScope | None = None,
        description_fa: str | None = None,
        max_redemptions: int | None = None,
        max_per_user: int = 1,
        redemption_count: int = 0,
        min_order_amount: Money | None = None,
        target_user_id: uuid.UUID | None = None,
        stacks_with_campaign: bool = True,
        first_purchase_only: bool = False,
        state: PublicationState = PublicationState.PUBLISHED,
        created_by: uuid.UUID | None = None,
        created_at: datetime | None = None,
    ) -> None:
        super().__init__(coupon_id)
        self.code = normalise_code(code)
        self.kind = kind
        self.discount = discount
        self.window = window or TimeWindow()
        self.scope = scope or PromotionScope()
        self.description_fa = description_fa
        self.max_per_user = max_per_user
        self.redemption_count = redemption_count
        self.min_order_amount = min_order_amount
        self.target_user_id = target_user_id
        self.stacks_with_campaign = stacks_with_campaign
        self.first_purchase_only = first_purchase_only
        self.state = state
        self.created_by = created_by
        self.created_at = created_at

        # SINGLE_USE means exactly one redemption. Silently rewriting a limit of
        # 99 to 1 was worse than refusing it: the operator saw the coupon saved
        # and believed 99 people could use it.
        if kind is CouponKind.SINGLE_USE:
            if max_redemptions not in (None, 1):
                raise CatalogValidationError(
                    "A single-use coupon cannot allow more than one redemption.",
                    code=self.code,
                    max_redemptions=max_redemptions,
                )
            self.max_redemptions = 1
        else:
            self.max_redemptions = max_redemptions

        if kind is CouponKind.TARGETED and target_user_id is None:
            raise CatalogValidationError(
                "A targeted coupon must name its recipient.", code=self.code
            )
        if kind is CouponKind.PER_USER and self.max_per_user != 1:
            raise CatalogValidationError(
                "A per-user coupon allows exactly one redemption per customer.",
                code=self.code,
            )

    # -- state -------------------------------------------------------------

    def archive(self) -> None:
        """Withdraw the coupon.

        Archiving rather than deleting: redemptions already reference it, and a
        dangling code on a past order is worse than a row nobody can use.
        """
        self.state = PublicationState.ARCHIVED

    @property
    def is_exhausted(self) -> bool:
        return self.max_redemptions is not None and self.redemption_count >= self.max_redemptions

    @property
    def remaining_redemptions(self) -> int | None:
        if self.max_redemptions is None:
            return None
        return max(0, self.max_redemptions - self.redemption_count)

    # -- validation --------------------------------------------------------

    def assert_redeemable(
        self,
        *,
        now: datetime,
        user_id: uuid.UUID,
        target: PromotionTarget,
        subtotal: Money,
        user_redemptions: int = 0,
        is_first_purchase: bool = False,
    ) -> None:
        """Raise the most specific reason this coupon cannot be used.

        Order matters. Checks are ordered from "nothing the customer can do" to
        "change your basket", so the message they see is the most actionable
        one available.
        """
        if self.state is not PublicationState.PUBLISHED:
            raise CouponExpired("This code is not active.", code=self.code)

        if self.window.has_ended(now):
            raise CouponExpired(
                "This code has expired.",
                code=self.code,
                expired_at=self.window.ends_at.isoformat() if self.window.ends_at else None,
            )

        if not self.window.has_started(now):
            raise CouponExpired(
                "This code is not valid yet.",
                code=self.code,
                starts_at=self.window.starts_at.isoformat() if self.window.starts_at else None,
            )

        if self.is_exhausted:
            raise CouponExhausted("This code has reached its usage limit.", code=self.code)

        if self.kind is CouponKind.TARGETED and self.target_user_id != user_id:
            # Same error as an unknown code on purpose: confirming that a code
            # exists but belongs to someone else invites enumeration.
            raise CouponNotApplicable("This code does not apply to your account.", code=self.code)

        if user_redemptions >= self.max_per_user:
            raise CouponExhausted(
                "You have already used this code.",
                code=self.code,
                max_per_user=self.max_per_user,
            )

        if self.first_purchase_only and not is_first_purchase:
            raise CouponNotApplicable(
                "This code is only valid on a first purchase.", code=self.code
            )

        if not self.scope.matches(
            plan_id=target.plan_id,
            product_id=target.product_id,
            tier=target.tier,
        ):
            raise CouponNotApplicable(
                "This code does not apply to the selected plan.", code=self.code
            )

        if self.min_order_amount is not None and subtotal < self.min_order_amount:
            raise CouponNotApplicable(
                "Your order is below the minimum for this code.",
                code=self.code,
                minimum=self.min_order_amount.amount,
            )

    def discount_for(self, subtotal: Money) -> Money:
        return self.discount.compute(subtotal)

    def redeem(self, *, user_id: uuid.UUID, discount: Money) -> None:
        self.redemption_count += 1
        self.record(
            CouponRedeemed(
                coupon_id=self.id,
                code=self.code,
                user_id=user_id,
                discount=discount.amount,
            )
        )
