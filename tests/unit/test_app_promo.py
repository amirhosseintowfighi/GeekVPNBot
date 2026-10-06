"""The Android app's offer banner, from the settings."""

from __future__ import annotations

from datetime import date

from geekvpn.presentation.api.routers.app_release import current_promo

TODAY = date(2026, 9, 29)


def test_no_title_no_banner():
    assert current_promo(title=" ", body="x", coupon="OFF", until="", today=TODAY) is None


def test_a_running_offer_with_its_coupon():
    promo = current_promo(
        title="۲۰٪ تخفیف", body="فقط این هفته", coupon=" AUTUMN ", until="2026-10-05", today=TODAY
    )
    assert promo is not None
    assert promo.coupon_code == "AUTUMN"
    assert promo.until == "2026-10-05"


def test_the_last_day_still_shows_and_the_next_does_not():
    assert current_promo(title="t", body="", coupon="", until="2026-09-29", today=TODAY) is not None
    assert current_promo(title="t", body="", coupon="", until="2026-09-28", today=TODAY) is None


def test_a_mistyped_date_hides_the_banner():
    assert current_promo(title="t", body="", coupon="", until="1405-07-07x", today=TODAY) is None


def test_without_a_coupon_or_a_date():
    promo = current_promo(title="t", body="b", coupon="", until="", today=TODAY)
    assert promo is not None
    assert promo.coupon_code is None
    assert promo.until is None
