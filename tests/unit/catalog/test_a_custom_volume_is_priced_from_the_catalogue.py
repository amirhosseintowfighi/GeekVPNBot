"""A customer-chosen volume, priced off the packages the operator already sells."""

from __future__ import annotations

import pytest

from geekvpn.domain.catalog.custom_volume import (
    MAX_CUSTOM_GIB,
    VolumePoint,
    minimum_gib,
    price_for_volume,
    total_gib,
)
from geekvpn.domain.catalog.errors import CatalogValidationError
from geekvpn.domain.catalog.money import Money

CATALOGUE = [
    VolumePoint(quota_gib=50, price=Money(400_000)),
    VolumePoint(quota_gib=20, price=Money(180_000)),
    VolumePoint(quota_gib=10, price=Money(100_000)),
]


def test_a_volume_between_two_packages_sits_on_the_line_between_them() -> None:
    assert price_for_volume(CATALOGUE, 35) == Money(290_000)


def test_a_volume_that_is_a_package_costs_exactly_that_package() -> None:
    assert price_for_volume(CATALOGUE, 20) == Money(180_000)


def test_the_smallest_package_is_the_minimum() -> None:
    assert minimum_gib(CATALOGUE) == 10
    with pytest.raises(CatalogValidationError):
        price_for_volume(CATALOGUE, 9)


def test_past_the_largest_package_its_own_rate_applies() -> None:
    # 400k for 50GB is 8k a GB; no further bulk discount is invented.
    assert price_for_volume(CATALOGUE, 100) == Money(800_000)


def test_an_absurd_volume_is_refused_rather_than_quoted() -> None:
    with pytest.raises(CatalogValidationError):
        price_for_volume(CATALOGUE, MAX_CUSTOM_GIB + 1)


def test_the_price_is_rounded_down_to_a_thousand() -> None:
    assert price_for_volume(CATALOGUE, 13) == Money(124_000)


def test_a_custom_volume_never_costs_less_than_a_smaller_package() -> None:
    upside_down = [
        VolumePoint(quota_gib=20, price=Money(300_000)),
        VolumePoint(quota_gib=50, price=Money(200_000)),
    ]
    assert price_for_volume(upside_down, 30) == Money(300_000)


def test_a_term_with_no_packages_cannot_price_anything() -> None:
    with pytest.raises(CatalogValidationError):
        price_for_volume([], 20)


def test_a_longer_term_carries_the_monthly_volume_for_every_month() -> None:
    assert total_gib(20, 90) == 60
    assert total_gib(20, 30) == 20
