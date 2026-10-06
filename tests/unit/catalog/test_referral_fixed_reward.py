"""A referrer can be paid a fixed amount instead of, or as well as, a share."""

from __future__ import annotations

import pytest

from geekvpn.application.platform.settings_service import SETTING_REGISTRY
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.rewards import ReferralPolicy

pytestmark = pytest.mark.unit


def test_a_fixed_reward_alone_pays_the_same_whatever_was_bought() -> None:
    policy = ReferralPolicy(first_purchase_bps=0, first_purchase_fixed=Money(50_000))

    assert policy.reward_for_order(paid=Money(100_000), is_first_purchase=True) == Money(50_000)
    assert policy.reward_for_order(paid=Money(900_000), is_first_purchase=True) == Money(50_000)


def test_a_share_and_a_fixed_amount_add_up() -> None:
    policy = ReferralPolicy(first_purchase_bps=1_000, first_purchase_fixed=Money(20_000))

    assert policy.reward_for_order(paid=Money(300_000), is_first_purchase=True) == Money(50_000)


def test_the_cap_still_applies_to_the_total() -> None:
    policy = ReferralPolicy(
        first_purchase_bps=1_000,
        first_purchase_fixed=Money(50_000),
        max_reward_per_order=Money(60_000),
    )

    assert policy.reward_for_order(paid=Money(300_000), is_first_purchase=True) == Money(60_000)


def test_later_orders_use_their_own_fixed_amount() -> None:
    policy = ReferralPolicy(first_purchase_fixed=Money(50_000), recurring_fixed=Money(10_000))

    assert policy.reward_for_order(paid=Money(100_000), is_first_purchase=False) == Money(10_000)


def test_the_referral_knobs_are_on_the_settings_screen() -> None:
    """They were read by the pricing engine and declared nowhere, so the
    admin panel could not show or change them."""
    keys = set(SETTING_REGISTRY)

    assert {
        "pricing.referral.first_purchase_bps",
        "pricing.referral.first_purchase_fixed",
        "pricing.referral.recurring_fixed",
    } <= keys
    assert SETTING_REGISTRY["pricing.referral.first_purchase_bps"].kind == "bps"
    assert SETTING_REGISTRY["pricing.referral.first_purchase_fixed"].kind == "toman"
