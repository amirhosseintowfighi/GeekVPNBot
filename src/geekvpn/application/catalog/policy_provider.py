"""Loads the pricing policy from runtime settings.

Every knob in `PricingPolicy` is an admin-editable runtime setting rather than
a constant, because these are exactly the values an operator wants to change at
11pm on the first night of a campaign. Requiring a deploy for "turn cashback
down to 5%" guarantees it will instead be done by editing rows in production.

The provider is fail-safe: a missing or malformed setting falls back to the
coded default rather than raising. A typo in one settings row must not take the
storefront down - it should just mean that one knob is at its default, which is
visible in the admin panel.
"""

from __future__ import annotations

from typing import Any, Final

import structlog

from geekvpn.application.ports.settings_store import SettingsStore
from geekvpn.domain.catalog.money import DEFAULT_ROUNDING_STEP, Money
from geekvpn.domain.catalog.pricing import PricingPolicy
from geekvpn.domain.catalog.rewards import CashbackPolicy, ReferralPolicy

logger = structlog.stdlib.get_logger(__name__)

# Settings keys. Namespaced so the admin panel can group them into sections.
KEY_ROUNDING_STEP: Final = "pricing.rounding_step"
KEY_ALLOW_STACKING: Final = "pricing.allow_coupon_campaign_stacking"
KEY_MAX_TOTAL_DISCOUNT_BPS: Final = "pricing.max_total_discount_bps"

KEY_CASHBACK_ENABLED: Final = "pricing.cashback.enabled"
KEY_CASHBACK_BASE_BPS: Final = "pricing.cashback.base_bps"
KEY_CASHBACK_MAX_BPS: Final = "pricing.cashback.max_bps"
KEY_CASHBACK_MAX_AMOUNT: Final = "pricing.cashback.max_amount"

KEY_REFERRAL_ENABLED: Final = "pricing.referral.enabled"
KEY_REFERRAL_SIGNUP_BONUS: Final = "pricing.referral.signup_bonus"
KEY_REFERRAL_FIRST_BPS: Final = "pricing.referral.first_purchase_bps"
KEY_REFERRAL_RECURRING_BPS: Final = "pricing.referral.recurring_bps"
KEY_REFERRAL_INVITEE_BONUS: Final = "pricing.referral.invitee_bonus"
KEY_REFERRAL_MAX_PER_ORDER: Final = "pricing.referral.max_reward_per_order"

#: Declared so the admin panel can render every knob even before it is written
#: once. Without this, a fresh install shows an empty settings page.
PRICING_SETTING_DEFAULTS: dict[str, Any] = {
    KEY_ROUNDING_STEP: DEFAULT_ROUNDING_STEP,
    KEY_ALLOW_STACKING: True,
    KEY_MAX_TOTAL_DISCOUNT_BPS: 7_000,
    KEY_CASHBACK_ENABLED: True,
    KEY_CASHBACK_BASE_BPS: 0,
    KEY_CASHBACK_MAX_BPS: 2_000,
    KEY_CASHBACK_MAX_AMOUNT: None,
    KEY_REFERRAL_ENABLED: True,
    KEY_REFERRAL_SIGNUP_BONUS: 0,
    KEY_REFERRAL_FIRST_BPS: 1_000,
    KEY_REFERRAL_RECURRING_BPS: 0,
    KEY_REFERRAL_INVITEE_BONUS: 0,
    KEY_REFERRAL_MAX_PER_ORDER: None,
}


class PricingPolicyProvider:
    """Assembles a `PricingPolicy` from the settings store."""

    def __init__(self, store: SettingsStore) -> None:
        self._store = store

    async def load(self) -> PricingPolicy:
        values = await self._read_all()

        cashback = CashbackPolicy(
            enabled=_as_bool(values, KEY_CASHBACK_ENABLED),
            base_bps=_as_int(values, KEY_CASHBACK_BASE_BPS),
            max_bps=_as_int(values, KEY_CASHBACK_MAX_BPS),
            max_amount=_as_money(values, KEY_CASHBACK_MAX_AMOUNT),
        )
        referral = ReferralPolicy(
            enabled=_as_bool(values, KEY_REFERRAL_ENABLED),
            signup_bonus=_as_money(values, KEY_REFERRAL_SIGNUP_BONUS) or Money.zero(),
            first_purchase_bps=_as_int(values, KEY_REFERRAL_FIRST_BPS),
            recurring_bps=_as_int(values, KEY_REFERRAL_RECURRING_BPS),
            invitee_bonus=_as_money(values, KEY_REFERRAL_INVITEE_BONUS) or Money.zero(),
            max_reward_per_order=_as_money(values, KEY_REFERRAL_MAX_PER_ORDER),
        )
        return PricingPolicy(
            rounding_step=_as_int(values, KEY_ROUNDING_STEP),
            allow_coupon_campaign_stacking=_as_bool(values, KEY_ALLOW_STACKING),
            max_total_discount_bps=_as_int(values, KEY_MAX_TOTAL_DISCOUNT_BPS),
            cashback=cashback,
            referral=referral,
        )

    async def _read_all(self) -> dict[str, Any]:
        """One read per key, each isolated from its neighbours.

        This used to go through `all()` inside a single blanket `except`, which
        meant any store that raised - or that implemented only `get()` - produced
        an all-defaults policy with nothing but one debug line to show for it. An
        operator who set a 50% ceiling would have been silently sold 70%.
        """
        values = dict(PRICING_SETTING_DEFAULTS)
        for key in PRICING_SETTING_DEFAULTS:
            try:
                record = await self._store.get(key)
            except Exception:
                logger.warning("pricing.setting_unreadable", key=key)
                continue
            if record is None:
                continue
            # Stores hand back a SettingRecord; test doubles hand back the value.
            values[key] = getattr(record, "value", record)
        return values


def _as_int(values: dict[str, Any], key: str) -> int:
    raw = values.get(key)
    try:
        if raw is None or isinstance(raw, bool):
            raise TypeError
        return int(raw)
    except (TypeError, ValueError):
        fallback = PRICING_SETTING_DEFAULTS[key]
        logger.warning("pricing.setting_invalid", key=key, value=repr(raw))
        return int(fallback or 0)


def _as_bool(values: dict[str, Any], key: str) -> bool:
    raw = values.get(key)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(raw, int):
        return raw != 0
    return bool(PRICING_SETTING_DEFAULTS[key])


def _as_money(values: dict[str, Any], key: str) -> Money | None:
    raw = values.get(key)
    if raw is None or raw == "":
        return None
    try:
        amount = int(raw)
    except (TypeError, ValueError):
        logger.warning("pricing.setting_invalid", key=key, value=repr(raw))
        return None
    return Money(amount) if amount > 0 else None
