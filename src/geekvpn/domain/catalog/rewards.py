"""Referral rewards, wallet cashback and loyalty tiers.

One rule governs this whole module: **rewards accrue, they do not discount.**

A 10% cashback is not a 10% price cut. The customer pays the full price, and
wallet credit appears afterwards. This matters for three reasons that are all
expensive to retrofit:

1. Revenue reporting stays truthful. A discount reduces revenue; cashback is a
   liability. Conflating them makes every margin number wrong.
2. Credit can be clawed back if the order is refunded, because it is a separate
   ledger entry rather than an adjustment baked into a price.
3. The customer comes back to spend it. That is the entire point of cashback,
   and it only works if the money is visibly sitting in their wallet.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field

from geekvpn.domain.catalog.enums import RewardTrigger
from geekvpn.domain.catalog.errors import CatalogValidationError
from geekvpn.domain.catalog.money import Money


class LoyaltyTier(enum.StrEnum):
    """Lifetime-spend tiers, branded in Persian in the storefront.

    Tiers change the *cashback rate*, never the price. A tiered price list is a
    support nightmare ("my friend sees 180,000 and I see 190,000"); a tiered
    reward is a visible, explicable benefit.
    """

    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    DIAMOND = "diamond"


#: Lifetime spend in Toman required to reach each tier.
TIER_THRESHOLDS: dict[LoyaltyTier, int] = {
    LoyaltyTier.BRONZE: 0,
    LoyaltyTier.SILVER: 1_000_000,
    LoyaltyTier.GOLD: 3_000_000,
    LoyaltyTier.DIAMOND: 10_000_000,
}

#: Extra cashback, in basis points, added to the plan's own rate.
TIER_CASHBACK_BONUS_BPS: dict[LoyaltyTier, int] = {
    LoyaltyTier.BRONZE: 0,
    LoyaltyTier.SILVER: 100,
    LoyaltyTier.GOLD: 250,
    LoyaltyTier.DIAMOND: 500,
}

TIER_LABEL_FA: dict[LoyaltyTier, str] = {
    LoyaltyTier.BRONZE: "برنزی",
    LoyaltyTier.SILVER: "نقره‌ای",
    LoyaltyTier.GOLD: "طلایی",
    LoyaltyTier.DIAMOND: "الماس",
}


def tier_for_spend(lifetime_spend: Money) -> LoyaltyTier:
    """Highest tier whose threshold the customer has met."""
    reached = LoyaltyTier.BRONZE
    for tier, threshold in TIER_THRESHOLDS.items():
        if lifetime_spend.amount >= threshold:
            reached = tier
    return reached


@dataclass(frozen=True, slots=True)
class CashbackPolicy:
    """How much wallet credit a purchase earns. Admin-configurable."""

    enabled: bool = True
    base_bps: int = 0
    """Platform-wide floor, added on top of whatever the plan itself offers."""

    max_bps: int = 2_000
    """Hard ceiling after plan rate, platform floor and tier bonus are summed.
    Without it, a 15% plan bought by a Diamond customer during a promotion
    quietly becomes 25%."""

    max_amount: Money | None = None
    """Absolute cap per order. Protects against a single very large purchase."""

    def __post_init__(self) -> None:
        if self.base_bps < 0 or self.max_bps < 0:
            raise CatalogValidationError("Cashback rates cannot be negative.")
        if self.max_bps > 10_000:
            raise CatalogValidationError("Cashback cannot exceed 100%.")
        if self.base_bps > self.max_bps:
            # effective_bps() clamps to max_bps, so this configuration used to be
            # accepted and then quietly ignored - the operator set 5% and got 1%.
            raise CatalogValidationError(
                "The cashback base rate cannot exceed its own ceiling.",
                base_bps=self.base_bps,
                max_bps=self.max_bps,
            )

    def effective_bps(self, *, plan_bps: int, tier: LoyaltyTier) -> int:
        if not self.enabled:
            return 0
        total = plan_bps + self.base_bps + TIER_CASHBACK_BONUS_BPS[tier]
        return min(total, self.max_bps)

    def compute(self, *, paid: Money, plan_bps: int, tier: LoyaltyTier) -> Money:
        bps = self.effective_bps(plan_bps=plan_bps, tier=tier)
        if bps == 0:
            return Money.zero()
        credit = paid.percentage(bps)
        if self.max_amount is not None and credit > self.max_amount:
            return self.max_amount
        return credit


@dataclass(frozen=True, slots=True)
class ReferralPolicy:
    """What a referrer earns, and when. Admin-configurable.

    The default deliberately pays nothing at signup and everything on the first
    purchase. Paying for signups is paying for bot accounts; paying for
    purchases is paying for customers.
    """

    enabled: bool = True
    signup_bonus: Money = field(default_factory=Money.zero)
    first_purchase_bps: int = 1_000
    """10% of the referred customer's first order, credited to the referrer."""

    recurring_bps: int = 0
    """Share of every subsequent order. Zero by default - lifetime revenue
    sharing is an obligation that is very hard to withdraw once advertised."""

    max_reward_per_order: Money | None = None
    invitee_bonus: Money = field(default_factory=Money.zero)
    """Credit for the new customer. Two-sided referrals convert far better,
    because the person doing the sharing has something to offer."""

    def __post_init__(self) -> None:
        for label, value in (
            ("first_purchase_bps", self.first_purchase_bps),
            ("recurring_bps", self.recurring_bps),
        ):
            if value < 0 or value > 10_000:
                raise CatalogValidationError(
                    f"{label} must be between 0 and 10000 basis points.",
                    field=label,
                    value=value,
                )

    def _cap(self, amount: Money) -> Money:
        if self.max_reward_per_order is not None and amount > self.max_reward_per_order:
            return self.max_reward_per_order
        return amount

    def reward_for_order(self, *, paid: Money, is_first_purchase: bool) -> Money:
        if not self.enabled:
            return Money.zero()
        bps = self.first_purchase_bps if is_first_purchase else self.recurring_bps
        if bps == 0:
            return Money.zero()
        return self._cap(paid.percentage(bps))


@dataclass(frozen=True, slots=True)
class RewardAccrual:
    """A single pending wallet credit.

    Deliberately not applied here. The pricing engine *calculates* accruals; the
    wallet ledger (Phase 5) is the only thing allowed to move money. Keeping
    calculation and mutation apart is what makes a quote safe to compute on
    every storefront page view.
    """

    trigger: RewardTrigger
    beneficiary_id: uuid.UUID
    amount: Money
    reason_fa: str

    @property
    def is_material(self) -> bool:
        return not self.amount.is_zero


def referral_accruals(
    *,
    paid: Money,
    buyer_id: uuid.UUID,
    referrer_id: uuid.UUID | None,
    policy: ReferralPolicy,
    is_first_purchase: bool,
) -> tuple[RewardAccrual, ...]:
    """Both sides of a referral for one order."""
    if not policy.enabled or referrer_id is None:
        return ()

    accruals: list[RewardAccrual] = []

    reward = policy.reward_for_order(paid=paid, is_first_purchase=is_first_purchase)
    if reward:
        accruals.append(
            RewardAccrual(
                trigger=RewardTrigger.REFERRAL_FIRST_PURCHASE
                if is_first_purchase
                else RewardTrigger.REFERRAL_SIGNUP,
                beneficiary_id=referrer_id,
                amount=reward,
                reason_fa="پاداش دعوت از دوستان",
            )
        )

    if is_first_purchase and policy.invitee_bonus:
        accruals.append(
            RewardAccrual(
                trigger=RewardTrigger.REFERRAL_SIGNUP,
                beneficiary_id=buyer_id,
                amount=policy.invitee_bonus,
                reason_fa="هدیه خوش‌آمدگویی دعوت",
            )
        )

    return tuple(accruals)
