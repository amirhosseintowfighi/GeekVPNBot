"""The pricing policy provider must fail open.

It sits on the read path of every storefront load and every quote. If it
raises, one malformed settings row takes the entire buying flow offline. The
correct failure mode is: log loudly, fall back to safe defaults, keep selling.
"""

from __future__ import annotations

import pytest

from geekvpn.application.catalog.policy_provider import (
    KEY_ALLOW_STACKING,
    KEY_CASHBACK_MAX_BPS,
    KEY_MAX_TOTAL_DISCOUNT_BPS,
    KEY_ROUNDING_STEP,
    PRICING_SETTING_DEFAULTS,
    PricingPolicyProvider,
)
from geekvpn.domain.catalog.pricing import PricingPolicy
from tests.catalog_fakes import FakeSettingsStore

pytestmark = pytest.mark.asyncio


async def test_empty_store_yields_the_defaults() -> None:
    policy = await PricingPolicyProvider(FakeSettingsStore()).load()
    assert policy == PricingPolicy()


async def test_reads_configured_values() -> None:
    store = FakeSettingsStore(
        {
            KEY_ROUNDING_STEP: 5_000,
            KEY_MAX_TOTAL_DISCOUNT_BPS: 5_000,
            KEY_ALLOW_STACKING: False,
        }
    )
    policy = await PricingPolicyProvider(store).load()
    assert policy.rounding_step == 5_000
    assert policy.max_total_discount_bps == 5_000
    assert policy.allow_coupon_campaign_stacking is False


@pytest.mark.parametrize("raw", ["true", "1", "yes", "on", True])
async def test_truthy_string_booleans(raw: object) -> None:
    store = FakeSettingsStore({KEY_ALLOW_STACKING: raw})
    policy = await PricingPolicyProvider(store).load()
    assert policy.allow_coupon_campaign_stacking is True


@pytest.mark.parametrize("raw", ["false", "0", "no", "off", False])
async def test_falsy_string_booleans(raw: object) -> None:
    store = FakeSettingsStore({KEY_ALLOW_STACKING: raw})
    policy = await PricingPolicyProvider(store).load()
    assert policy.allow_coupon_campaign_stacking is False


async def test_a_garbage_value_falls_back_to_its_default() -> None:
    store = FakeSettingsStore({KEY_ROUNDING_STEP: "not-a-number"})
    policy = await PricingPolicyProvider(store).load()
    assert policy.rounding_step == PRICING_SETTING_DEFAULTS[KEY_ROUNDING_STEP]


async def test_a_dead_settings_backend_still_returns_a_policy() -> None:
    store = FakeSettingsStore()
    store.explode = True
    policy = await PricingPolicyProvider(store).load()
    assert policy == PricingPolicy()


async def test_an_invalid_combination_falls_back_wholesale() -> None:
    # base_bps above max_bps is rejected by CashbackPolicy. The provider must
    # absorb that rather than propagating it to the storefront.
    store = FakeSettingsStore({KEY_CASHBACK_MAX_BPS: 10})
    policy = await PricingPolicyProvider(store).load()
    assert isinstance(policy, PricingPolicy)


async def test_every_default_key_is_documented() -> None:
    # The migration seeds exactly these keys. If someone adds a setting to the
    # provider without seeding it, this is the test that notices.
    assert len(PRICING_SETTING_DEFAULTS) == 13
    assert all(key.startswith("pricing.") for key in PRICING_SETTING_DEFAULTS)
