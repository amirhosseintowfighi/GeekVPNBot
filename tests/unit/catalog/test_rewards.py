"""Loyalty tiers, wallet cashback and referral rewards.

The governing rule: rewards **accrue**, they do not discount. Cashback and
referral bonuses land in the wallet after the fact; they never reduce the
invoice. Mixing the two makes revenue reporting meaningless, because the amount
charged would no longer match the amount recognised.
"""

from __future__ import annotations

import uuid

import pytest

from geekvpn.domain.catalog.errors import CatalogValidationError
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.rewards import (
    TIER_LABEL_FA,
    CashbackPolicy,
    LoyaltyTier,
    ReferralPolicy,
    RewardTrigger,
    referral_accruals,
    tier_for_spend,
)


class TestLoyaltyTiers:
    @pytest.mark.parametrize(
        ("spend", "expected"),
        [
            (0, LoyaltyTier.BRONZE),
            (999_999, LoyaltyTier.BRONZE),
            (1_000_000, LoyaltyTier.SILVER),
            (2_999_999, LoyaltyTier.SILVER),
            (3_000_000, LoyaltyTier.GOLD),
            (9_999_999, LoyaltyTier.GOLD),
            (10_000_000, LoyaltyTier.DIAMOND),
            (50_000_000, LoyaltyTier.DIAMOND),
        ],
    )
    def test_thresholds(self, spend: int, expected: LoyaltyTier) -> None:
        assert tier_for_spend(Money(spend)) is expected

    def test_every_tier_has_a_persian_label(self) -> None:
        # The tier name is shown in the Mini App header; a missing label would
        # render an English enum value in a fully Persian UI.
        for tier in LoyaltyTier:
            assert TIER_LABEL_FA[tier]


class TestCashback:
    def test_bronze_gets_only_the_plan_rate(self) -> None:
        policy = CashbackPolicy(base_bps=0, max_bps=2_000)
        assert policy.effective_bps(plan_bps=500, tier=LoyaltyTier.BRONZE) == 500

    def test_gold_adds_a_tier_bonus(self) -> None:
        policy = CashbackPolicy(base_bps=0, max_bps=2_000)
        assert policy.effective_bps(plan_bps=500, tier=LoyaltyTier.GOLD) == 750

    def test_ceiling_caps_the_combined_rate(self) -> None:
        policy = CashbackPolicy(base_bps=0, max_bps=2_000)
        assert policy.effective_bps(plan_bps=1_900, tier=LoyaltyTier.DIAMOND) == 2_000

    def test_disabled_pays_nothing(self) -> None:
        policy = CashbackPolicy(enabled=False)
        paid = policy.compute(paid=Money(680_000), plan_bps=500, tier=LoyaltyTier.DIAMOND)
        assert paid.is_zero

    def test_absolute_cap(self) -> None:
        policy = CashbackPolicy(max_amount=Money(10_000))
        assert policy.compute(
            paid=Money(680_000), plan_bps=1_000, tier=LoyaltyTier.BRONZE
        ) == Money(10_000)

    def test_base_rate_cannot_exceed_the_ceiling(self) -> None:
        with pytest.raises(CatalogValidationError):
            CashbackPolicy(base_bps=500, max_bps=100)


class TestReferral:
    def test_first_purchase_pays_both_sides(self) -> None:
        buyer, referrer = uuid.uuid4(), uuid.uuid4()
        policy = ReferralPolicy(first_purchase_bps=1_000, invitee_bonus=Money(20_000))
        accruals = referral_accruals(
            paid=Money(680_000),
            buyer_id=buyer,
            referrer_id=referrer,
            policy=policy,
            is_first_purchase=True,
        )
        assert len(accruals) == 2
        by_user = {a.beneficiary_id: a for a in accruals}
        assert by_user[referrer].amount == Money(68_000)
        assert by_user[buyer].amount == Money(20_000)

    def test_no_referrer_means_no_accruals(self) -> None:
        accruals = referral_accruals(
            paid=Money(680_000),
            buyer_id=uuid.uuid4(),
            referrer_id=None,
            policy=ReferralPolicy(),
            is_first_purchase=True,
        )
        assert accruals == ()

    def test_zero_accruals_are_dropped(self) -> None:
        # Storing a 0-Toman wallet credit is noise in the ledger and a
        # confusing "you earned 0" notification.
        accruals = referral_accruals(
            paid=Money(680_000),
            buyer_id=uuid.uuid4(),
            referrer_id=uuid.uuid4(),
            policy=ReferralPolicy(recurring_bps=0),
            is_first_purchase=False,
        )
        assert accruals == ()

    def test_recurring_rate_on_repeat_orders(self) -> None:
        referrer = uuid.uuid4()
        accruals = referral_accruals(
            paid=Money(680_000),
            buyer_id=uuid.uuid4(),
            referrer_id=referrer,
            policy=ReferralPolicy(recurring_bps=500),
            is_first_purchase=False,
        )
        assert len(accruals) == 1
        assert accruals[0].amount == Money(34_000)

    def test_per_order_cap(self) -> None:
        policy = ReferralPolicy(first_purchase_bps=5_000, max_reward_per_order=Money(30_000))
        assert policy.reward_for_order(paid=Money(2_000_000), is_first_purchase=True) == Money(
            30_000
        )

    def test_disabled_policy_pays_nothing(self) -> None:
        accruals = referral_accruals(
            paid=Money(680_000),
            buyer_id=uuid.uuid4(),
            referrer_id=uuid.uuid4(),
            policy=ReferralPolicy(enabled=False),
            is_first_purchase=True,
        )
        assert accruals == ()

    def test_accruals_carry_a_persian_reason(self) -> None:
        accruals = referral_accruals(
            paid=Money(680_000),
            buyer_id=uuid.uuid4(),
            referrer_id=uuid.uuid4(),
            policy=ReferralPolicy(first_purchase_bps=1_000),
            is_first_purchase=True,
        )
        assert all(a.reason_fa for a in accruals)
        assert all(a.trigger in set(RewardTrigger) for a in accruals)
