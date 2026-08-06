"""Money arithmetic.

This is the most boring file in the repository and the one most worth having.
Every price the customer sees comes out of these operations, and a rounding
error here is a rounding error on every invoice.

The representation is an integer count of Toman. No floats appear anywhere in
the pricing path - 0.1 + 0.2 must never be allowed near a currency.
"""

from __future__ import annotations

import pytest

from geekvpn.domain.catalog.errors import CatalogValidationError
from geekvpn.domain.catalog.money import CURRENCY, Money


class TestConstruction:
    def test_rejects_negative_amounts(self) -> None:
        # There is no such thing as a negative price. A refund is a separate
        # ledger entry, not a negative Money.
        with pytest.raises(CatalogValidationError):
            Money(-1)

    def test_rejects_fractional_amounts(self) -> None:
        with pytest.raises(CatalogValidationError):
            Money(1.5)  # type: ignore[arg-type]

    def test_rejects_bool(self) -> None:
        # bool is a subclass of int in Python, so Money(True) would silently
        # become 1 Toman without an explicit guard.
        with pytest.raises(CatalogValidationError):
            Money(True)  # type: ignore[arg-type]

    def test_zero(self) -> None:
        assert Money.zero().amount == 0
        assert Money.zero().is_zero


class TestArithmetic:
    def test_addition(self) -> None:
        assert Money(100) + Money(50) == Money(150)

    def test_subtraction_clamps_at_zero(self) -> None:
        # Subtracting a bigger discount than the subtotal must floor at zero,
        # not produce a negative price the customer would be "paid".
        assert (Money(100) - Money(250)).amount == 0

    def test_multiplication(self) -> None:
        assert Money(1_000) * 3 == Money(3_000)
        assert 3 * Money(1_000) == Money(3_000)

    def test_ordering(self) -> None:
        assert Money(100) < Money(200)
        assert max(Money(100), Money(900)) == Money(900)


class TestPercentage:
    def test_basic_percentage(self) -> None:
        assert Money(680_000).percentage(1_500) == Money(102_000)

    def test_rounds_half_up(self) -> None:
        # 1005 * 50% = 502.5. Half-up gives 503.
        assert Money(1_005).percentage(5_000) == Money(503)

    def test_zero_percent(self) -> None:
        assert Money(680_000).percentage(0).is_zero

    def test_hundred_percent(self) -> None:
        assert Money(680_000).percentage(10_000) == Money(680_000)


class TestRounding:
    def test_rounds_down_never_up(self) -> None:
        # Always in the customer's favour. Rounding a price up to a neater
        # number is a price increase nobody agreed to.
        assert Money(187_999).round_to(1_000) == Money(187_000)

    def test_already_round_is_unchanged(self) -> None:
        assert Money(187_000).round_to(1_000) == Money(187_000)

    def test_below_step_rounds_to_zero(self) -> None:
        assert Money(999).round_to(1_000).is_zero

    def test_step_of_one_is_identity(self) -> None:
        assert Money(187_999).round_to(1) == Money(187_999)


class TestFormatting:
    def test_str_uses_thousands_separators(self) -> None:
        assert str(Money(1_234_567)) == f"1,234,567 {CURRENCY}"
