"""Money.

The single most important decision in this file: **money is an integer number
of Toman**. Never a float.

Floats cannot represent 0.1 exactly. A pricing pipeline that applies a 30%
campaign discount, then a 10% coupon, then 9% cashback in floating point will
drift, and the drift lands in a customer's invoice. Every currency system that
has ever been debugged at 3am arrived at the same answer: integers, with
rounding applied explicitly and only where the domain says to round.

Why Toman and not Rial: Iranian customers think, speak and pay in Toman. The
official currency is the Rial (1 Toman = 10 Rial), and a system that stores
Rial must divide by ten on every single display. We store what we quote.

There are no sub-Toman amounts in Iranian retail, so the integer *is* the
smallest unit. That removes the minor-unit bookkeeping entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from geekvpn.domain.catalog.errors import CatalogValidationError

CURRENCY: Final[str] = "IRT"
"""ISO-ish code for Toman. Not an official ISO 4217 code (that is IRR for Rial),
but unambiguous internally and never shown to customers."""

DEFAULT_ROUNDING_STEP: Final[int] = 1_000
"""Iranian retail prices are quoted in thousands. A quote of 187,432 Toman looks
broken; 187,000 looks deliberate."""


@dataclass(frozen=True, slots=True, order=True)
class Money:
    """A non-negative amount of Toman.

    Negative money is not representable. A refund is a credit *entry* with a
    direction, not a negative amount - that distinction keeps ledger sums
    honest and makes an accidental sign flip impossible.
    """

    amount: int

    def __post_init__(self) -> None:
        if not isinstance(self.amount, int) or isinstance(self.amount, bool):
            raise CatalogValidationError(
                "Money must be a whole number of Toman.",
                amount=repr(self.amount),
            )
        if self.amount < 0:
            raise CatalogValidationError("Money cannot be negative.", amount=self.amount)

    # -- construction ------------------------------------------------------

    @classmethod
    def zero(cls) -> Money:
        return cls(0)

    @classmethod
    def of(cls, amount: int) -> Money:
        return cls(amount)

    # -- arithmetic --------------------------------------------------------

    def __add__(self, other: Money) -> Money:
        return Money(self.amount + other.amount)

    def __sub__(self, other: Money) -> Money:
        """Subtraction clamps at zero.

        A discount larger than the price yields a free order, not a debt. The
        caller that cares about the overshoot compares before subtracting.
        """
        return Money(max(0, self.amount - other.amount))

    def __mul__(self, factor: int) -> Money:
        if not isinstance(factor, int) or isinstance(factor, bool):
            raise CatalogValidationError(
                "Money may only be multiplied by a whole number.", factor=repr(factor)
            )
        return Money(self.amount * factor)

    __rmul__ = __mul__

    def percentage(self, basis_points: int) -> Money:
        """Take a percentage expressed in basis points, rounded half-up.

        Basis points (1 bp = 0.01%) rather than a float percentage, so that
        "12.5% off" is the exact integer 1250 and survives a database round
        trip unchanged.

        Rounding is half-up on the absolute value, which for non-negative money
        is plain half-up. Banker's rounding is correct for repeated sums of
        signed values; for a single customer-facing discount it produces the
        surprising result that 2.5 rounds to 2.
        """
        if basis_points < 0:
            raise CatalogValidationError(
                "Basis points cannot be negative.", basis_points=basis_points
            )
        return Money((self.amount * basis_points + 5_000) // 10_000)

    def round_to(self, step: int = DEFAULT_ROUNDING_STEP) -> Money:
        """Round **down** to a multiple of ``step``.

        Down, not nearest. Rounding a customer-facing price up after we have
        already shown them a discount is the kind of small dishonesty that
        generates support tickets and screenshots. Rounding down costs us at
        most 999 Toman and always looks generous.
        """
        if step <= 0:
            raise CatalogValidationError("Rounding step must be positive.", step=step)
        return Money((self.amount // step) * step)

    # -- predicates --------------------------------------------------------

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    def __bool__(self) -> bool:
        return self.amount != 0

    def __str__(self) -> str:
        return f"{self.amount:,} {CURRENCY}"

    def __repr__(self) -> str:
        return f"Money({self.amount})"


#: Readable alias at call sites that would otherwise say `Money(120_000)`.
Toman = Money
