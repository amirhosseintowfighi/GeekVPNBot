"""The bot's custom-volume step: what it accepts and what it offers."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from geekvpn.presentation.bot.handlers.purchase import _one_package_per_term, _typed_gib
from geekvpn.presentation.bot.handlers.shop import custom_floor

pytestmark = pytest.mark.unit


def _plan(*, gib: int | None, days: int, kind: str = "traffic") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), plan_type=kind, quota_gib=gib, duration_days=days)


def _category(*plans: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(products=[SimpleNamespace(plans=list(plans))])


@pytest.mark.parametrize("typed", ["35", "۳۵", "35GB", "۳۵ گیگ", " 35 gb "])
def test_a_volume_is_understood_however_it_is_typed(typed: str) -> None:
    assert _typed_gib(typed) == 35


@pytest.mark.parametrize("typed", ["", "abc", "0", "-5", "3.5", "99999999"])
def test_anything_that_is_not_a_sane_volume_is_refused(typed: str) -> None:
    assert _typed_gib(typed) is None


def test_the_floor_is_the_smallest_monthly_package() -> None:
    category = _category(_plan(gib=20, days=30), _plan(gib=10, days=30), _plan(gib=30, days=90))
    assert custom_floor(category) == 10


def test_a_category_of_unlimited_time_offers_no_custom_volume() -> None:
    assert custom_floor(_category(_plan(gib=None, days=30, kind="unlimited"))) is None


def test_every_term_is_offered_once_shortest_first() -> None:
    category = _category(_plan(gib=60, days=90), _plan(gib=10, days=30), _plan(gib=20, days=30))
    assert [p.duration_days for p in _one_package_per_term(category)] == [30, 90]
