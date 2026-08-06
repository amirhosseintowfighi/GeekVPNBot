"""The duration ladder.

These tests encode the commercial reasoning, not just the arithmetic - if
someone later flattens the curve or slips a 60-day rung in, the reason it was
rejected is written down right here.
"""

from __future__ import annotations

import itertools

import pytest

from geekvpn.domain.catalog import durations as D

MONTHLY_PRICE = 200_000


class TestLadderShape:
    def test_is_ordered_shortest_to_longest(self) -> None:
        days = [rung.days for rung in D.LADDER]
        assert days == sorted(days)

    def test_expected_rungs(self) -> None:
        assert [r.days for r in D.LADDER] == [7, 30, 90, 180, 365]

    def test_sixty_days_is_deliberately_absent(self) -> None:
        """60d sits too close to 30d to be a real decision and cannibalises
        it. If this ever comes back it should be a conscious choice."""
        assert D.rung_for_days(60) is None

    def test_default_ladder_excludes_weekly(self) -> None:
        assert D.WEEKLY not in D.DEFAULT_LADDER

    def test_default_ladder_is_a_subset(self) -> None:
        assert set(D.DEFAULT_LADDER).issubset(set(D.LADDER))

    def test_slugs_are_unique(self) -> None:
        slugs = [r.slug for r in D.LADDER]
        assert len(slugs) == len(set(slugs))

    def test_lookup_tables_agree(self) -> None:
        for rung in D.LADDER:
            assert D.BY_SLUG[rung.slug] is rung
            assert D.BY_DAYS[rung.days] is rung


class TestPricing:
    def test_monthly_is_the_baseline(self) -> None:
        assert D.MONTHLY.price_from_monthly(MONTHLY_PRICE) == MONTHLY_PRICE

    def test_weekly_costs_more_per_day(self) -> None:
        """The one rung with a premium instead of a discount."""
        weekly = D.WEEKLY.price_from_monthly(MONTHLY_PRICE)
        straight = MONTHLY_PRICE * 7 / 30
        assert weekly > straight

    def test_weekly_savings_are_negative(self) -> None:
        assert D.WEEKLY.savings_from_monthly(MONTHLY_PRICE) < 0

    def test_longer_terms_cost_more_in_absolute_terms(self) -> None:
        """A longer package must never be cheaper outright, or the shorter
        one becomes unsellable."""
        prices = [r.price_from_monthly(MONTHLY_PRICE) for r in D.DEFAULT_LADDER]
        assert prices == sorted(prices)

    def test_effective_monthly_rate_falls(self) -> None:
        """The actual promise to the customer: longer means cheaper per month."""
        rates = [D.effective_monthly_price(MONTHLY_PRICE, r) for r in D.DEFAULT_LADDER]
        assert rates == sorted(rates, reverse=True)

    def test_annual_saves_about_a_quarter(self) -> None:
        saved = D.ANNUAL.savings_from_monthly(MONTHLY_PRICE)
        straight = int(MONTHLY_PRICE * 365 / 30)
        assert saved / straight == pytest.approx(0.25, abs=0.01)


class TestCurveIsConcave:
    def test_discount_increases_with_term(self) -> None:
        bps = [r.discount_bps for r in D.DEFAULT_LADDER]
        assert bps == sorted(bps)

    def test_marginal_discount_per_month_shrinks(self) -> None:
        """Concavity. A linear curve makes the annual plan too cheap relative
        to the churn protection it buys."""
        rungs = list(D.DEFAULT_LADDER)
        marginal = []
        for previous, current in itertools.pairwise(rungs):
            extra_months = current.months - previous.months
            gain = current.discount_bps - previous.discount_bps
            marginal.append(gain / extra_months)
        assert marginal == sorted(marginal, reverse=True)


class TestPerks:
    def test_only_long_terms_grant_devices(self) -> None:
        assert D.MONTHLY.bonus_devices == 0
        assert D.QUARTERLY.bonus_devices == 0
        assert D.SEMIANNUAL.bonus_devices >= 1
        assert D.ANNUAL.bonus_devices >= D.SEMIANNUAL.bonus_devices

    def test_headline_rungs_are_badged(self) -> None:
        assert D.SEMIANNUAL.badge_fa
        assert D.ANNUAL.badge_fa

    def test_baseline_has_no_badge(self) -> None:
        """If everything is highlighted, nothing is."""
        assert D.MONTHLY.badge_fa is None
