"""Promotion scope: which plans a discount is allowed to touch.

Coupons and campaigns need the identical targeting rules, so the rules live here
once. Duplicating them would guarantee that a bug fixed in one is left in the
other - promotion targeting is exactly the kind of logic nobody re-reads.

An empty scope means "everything". That is a deliberate default: the common case
is a site-wide sale, and forcing an operator to enumerate every plan for the
common case is how stale promotions that miss newly added plans get created.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from geekvpn.domain.catalog.enums import ProductTier


@dataclass(frozen=True, slots=True)
class PromotionScope:
    """Targeting rules, evaluated as a union.

    If any of the three sets is non-empty, the promotion applies to a plan when
    it matches **any** populated dimension. Union rather than intersection
    because operators think in terms of "this sale covers the Turbo tier and
    also that one specific Direct package".
    """

    plan_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    product_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    tiers: frozenset[ProductTier] = field(default_factory=frozenset)

    @property
    def is_global(self) -> bool:
        return not (self.plan_ids or self.product_ids or self.tiers)

    def matches(self, *, plan_id: uuid.UUID, product_id: uuid.UUID, tier: ProductTier) -> bool:
        if self.is_global:
            return True
        return plan_id in self.plan_ids or product_id in self.product_ids or tier in self.tiers

    def matches_target(self, target: PromotionTarget) -> bool:
        """Same rule as `matches`, taking the already-assembled target.

        Callers that hold a `PromotionTarget` had to unpack it into three keyword
        arguments, which is where a silent mix-up of plan_id and product_id lives.
        """
        return self.matches(
            plan_id=target.plan_id,
            product_id=target.product_id,
            tier=target.tier,
        )


@dataclass(frozen=True, slots=True)
class PromotionTarget:
    """The thing being priced, reduced to just what targeting needs.

    Passing this instead of the full `Plan` and `Product` keeps the pricing
    engine testable without constructing an entire catalogue, and prevents
    targeting logic from quietly growing a dependency on, say, marketing copy.
    """

    plan_id: uuid.UUID
    product_id: uuid.UUID
    tier: ProductTier
