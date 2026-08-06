"""Cohorts, churn and lifetime value.

Retention is measured by *renewal*, not by activity. A customer with 40 days
left on a yearly plan is not "retained" by logging in; they are retained when
they pay again. Anything else flatters the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from geekvpn.domain.analytics.calendar import fa_digits
from geekvpn.domain.analytics.metrics import ratio_percent, safe_divide

CHURN_GRACE_DAYS = 14
"""Days after expiry before a silent customer is called churned.

Card-to-card renewal is manual and people are slow; counting someone as lost
the morning after expiry would overstate churn badly.
"""

AT_RISK_DAYS = 7


@dataclass(frozen=True, slots=True)
class CohortCell:
    """One month of one cohort's life."""

    period: int
    retained: int
    cohort_size: int

    @property
    def rate(self) -> float:
        return ratio_percent(self.retained, self.cohort_size)

    def as_dict(self) -> dict[str, Any]:
        return {"period": self.period, "retained": self.retained, "rate": self.rate}


@dataclass(frozen=True, slots=True)
class Cohort:
    """Everyone who first paid in the same month."""

    key: str
    label_fa: str
    size: int
    cells: tuple[CohortCell, ...] = ()

    @classmethod
    def build(cls, *, key: str, label_fa: str, size: int, retained: tuple[int, ...]) -> Cohort:
        cells = tuple(
            CohortCell(period=index, retained=min(value, size), cohort_size=size)
            for index, value in enumerate(retained)
        )
        return cls(key=key, label_fa=label_fa, size=size, cells=cells)

    def rate_at(self, period: int) -> float:
        for cell in self.cells:
            if cell.period == period:
                return cell.rate
        return 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "labelFa": self.label_fa,
            "size": self.size,
            "cells": [cell.as_dict() for cell in self.cells],
        }


@dataclass(frozen=True, slots=True)
class CohortTable:
    """The triangular retention grid the analytics screen renders."""

    cohorts: tuple[Cohort, ...] = ()

    @property
    def periods(self) -> int:
        return max((len(cohort.cells) for cohort in self.cohorts), default=0)

    def average_rate_at(self, period: int) -> float:
        """Weighted by cohort size -- a five-person cohort must not dominate."""
        retained = 0
        total = 0
        for cohort in self.cohorts:
            for cell in cohort.cells:
                if cell.period == period:
                    retained += cell.retained
                    total += cell.cohort_size
        return ratio_percent(retained, total)

    def curve(self) -> tuple[float, ...]:
        return tuple(self.average_rate_at(period) for period in range(self.periods))

    def as_dict(self) -> dict[str, Any]:
        return {
            "periods": self.periods,
            "curve": list(self.curve()),
            "cohorts": [cohort.as_dict() for cohort in self.cohorts],
        }


@dataclass(frozen=True, slots=True)
class RetentionSummary:
    """Headline retention numbers for one period."""

    active_start: int = 0
    active_end: int = 0
    expired: int = 0
    renewed: int = 0
    churned: int = 0
    new_customers: int = 0
    net_revenue: int = 0
    lifetime_months: float = 0.0

    @property
    def renewal_rate(self) -> float:
        """Of the subscriptions that came up for renewal, how many did."""
        return ratio_percent(self.renewed, self.expired)

    @property
    def churn_rate(self) -> float:
        return ratio_percent(self.churned, self.active_start)

    @property
    def growth_rate(self) -> float:
        return ratio_percent(self.active_end - self.active_start, self.active_start)

    @property
    def average_revenue_per_customer(self) -> float:
        return safe_divide(self.net_revenue, max(1, self.active_end))

    @property
    def lifetime_value(self) -> float:
        """ARPU times expected lifetime.

        Lifetime is derived from churn (``1 / churn``) when we have a churn
        figure, and falls back to the observed average tenure otherwise.
        """
        monthly = self.average_revenue_per_customer
        if self.churn_rate > 0:
            return monthly * (100.0 / self.churn_rate)
        return monthly * max(1.0, self.lifetime_months)

    def headline_fa(self) -> str:
        return (
            f"\u0646\u0631\u062e \u062a\u0645\u062f\u06cc\u062f "
            f"{fa_digits(round(self.renewal_rate))}\u066a"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "activeStart": self.active_start,
            "activeEnd": self.active_end,
            "expired": self.expired,
            "renewed": self.renewed,
            "churned": self.churned,
            "newCustomers": self.new_customers,
            "renewalRate": self.renewal_rate,
            "churnRate": self.churn_rate,
            "growthRate": self.growth_rate,
            "ltv": self.lifetime_value,
        }


def is_churned(days_since_expiry: int) -> bool:
    return days_since_expiry > CHURN_GRACE_DAYS


def is_at_risk(days_to_expiry: int) -> bool:
    return 0 <= days_to_expiry <= AT_RISK_DAYS


__all__ = [
    "AT_RISK_DAYS",
    "CHURN_GRACE_DAYS",
    "Cohort",
    "CohortCell",
    "CohortTable",
    "RetentionSummary",
    "is_at_risk",
    "is_churned",
]
