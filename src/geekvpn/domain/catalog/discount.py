"""A discount rule: percentage or fixed amount, with an optional ceiling.

Shared by coupons and campaigns. The ceiling exists because "50% off" on a
two-year Elite package is a very different amount of money than on a one-month
Direct package, and operators reliably forget that until it has happened.
"""

from __future__ import annotations

from dataclasses import dataclass

from geekvpn.domain.catalog.enums import DiscountKind
from geekvpn.domain.catalog.errors import CatalogValidationError
from geekvpn.domain.catalog.money import Money

MAX_PERCENTAGE_BPS = 10_000


@dataclass(frozen=True, slots=True)
class Discount:
    """How much to take off, expressed so it can never be ambiguous.

    ``value`` means basis points for ``PERCENTAGE`` and Toman for
    ``FIXED_AMOUNT``. A single integer field with a discriminator beats two
    nullable fields: there is no state in which both are set, or neither.
    """

    kind: DiscountKind
    value: int
    max_discount: Money | None = None

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise CatalogValidationError("A discount must remove something.", value=self.value)
        if self.kind is DiscountKind.PERCENTAGE and self.value > MAX_PERCENTAGE_BPS:
            raise CatalogValidationError(
                "A percentage discount cannot exceed 100%.",
                basis_points=self.value,
            )

    @classmethod
    def percentage(cls, basis_points: int, *, cap: Money | None = None) -> Discount:
        return cls(DiscountKind.PERCENTAGE, basis_points, cap)

    @classmethod
    def fixed(cls, amount: int) -> Discount:
        return cls(DiscountKind.FIXED_AMOUNT, amount)

    def compute(self, subtotal: Money) -> Money:
        """The amount to deduct, never more than the subtotal itself."""
        if self.kind is DiscountKind.PERCENTAGE:
            raw = subtotal.percentage(self.value)
        else:
            raw = Money(self.value)

        if self.max_discount is not None and raw > self.max_discount:
            raw = self.max_discount

        # Clamp: a fixed 100,000 discount on a 50,000 plan makes it free, not
        # a 50,000 credit. Credit must be an explicit wallet operation.
        return raw if raw <= subtotal else subtotal

    @property
    def label(self) -> str:
        if self.kind is DiscountKind.PERCENTAGE:
            whole = self.value // 100
            fraction = self.value % 100
            return f"{whole}%" if fraction == 0 else f"{self.value / 100:g}%"
        return f"{self.value:,}"
