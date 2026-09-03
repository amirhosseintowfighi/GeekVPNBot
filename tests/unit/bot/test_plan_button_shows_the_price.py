"""The price survives on a package button.

Telegram gives an inline button one line and truncates the rest. With the price
written last the price was what disappeared, and the shop's buttons read
"۲۰ گیگابایت · یک‌ماهه · ۲۰۰,..." - a storefront where the one number the
customer is deciding on is the one they cannot see.
"""

from __future__ import annotations

import pytest

from geekvpn.presentation.bot.ui.fa import gib
from geekvpn.presentation.bot.ui.render import plan_button_label

pytestmark = pytest.mark.unit


class FakePrice:
    def __init__(self, total: int, campaign_label: str | None = None) -> None:
        self.total = total
        self.campaign_label = campaign_label


class FakePlan:
    def __init__(
        self,
        *,
        total: int = 200_000,
        quota_gib: float | None = 20,
        duration_days: int = 30,
        featured: bool = False,
        campaign: str | None = None,
    ) -> None:
        self.price = FakePrice(total, campaign)
        self.quota_gib = quota_gib
        self.duration_days = duration_days
        self.is_featured = featured


#: The bidi isolates that wrap every formatted run. Invisible to a reader and
#: to Telegram's line measurement, so they are stripped before comparing.
INVISIBLE = "⁨⁩‎‏"


def _visible(label: str) -> str:
    return "".join(ch for ch in label if ch not in INVISIBLE)


def test_the_price_comes_first():
    """Whatever else is cut, this is not."""
    label = _visible(plan_button_label(FakePlan()))

    assert label.startswith("۲۰۰,۰۰۰"), label


def test_the_label_is_shorter_than_it_was():
    """The old order, reconstructed. If this stops being an improvement the
    change has been undone."""
    plan = FakePlan()
    old = _visible(f"{gib(20)} · یک‌ماهه · ۲۰۰,۰۰۰ تومان")

    assert len(_visible(plan_button_label(plan))) < len(old)


def test_the_quota_and_duration_are_still_there():
    label = plan_button_label(FakePlan())

    assert "گیگ" in label
    assert "ماه" in label


def test_a_featured_package_still_gets_its_star():
    label = plan_button_label(FakePlan(featured=True))

    assert label.startswith("⭐")


def test_a_campaign_beats_featured_for_the_prefix():
    """One badge per button. A package can be both, and two symbols eat the
    line this whole change is about."""
    label = plan_button_label(FakePlan(featured=True, campaign="جمعه"))

    assert not label.startswith("⭐")


def test_an_unlimited_package_says_so_rather_than_zero():
    label = plan_button_label(FakePlan(quota_gib=None))

    assert "نامحدود" in label


def test_the_compact_unit_is_only_for_buttons():
    """The full word stays everywhere there is room for it, so the detail page
    does not start speaking in abbreviations."""
    assert "گیگابایت" in gib(20)
    assert "گیگابایت" not in gib(20, compact=True)
