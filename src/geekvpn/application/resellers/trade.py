"""A reseller's own trade, as charts for their panel.

The portal had four all-time sums and nothing over time, so a reseller could
not see whether this week was better than last, which packages sell, or
whether their bot is still bringing in customers. These are the platform
dashboard's charts, cut to one reseller's rows - never a door into anyone
else's figures, which is why this reads by reseller id and nothing wider.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from geekvpn.domain.analytics.series import BreakdownSlice, TimeSeries
from geekvpn.domain.analytics.timeframe import DateRange


@dataclass(frozen=True, slots=True)
class ResellerTrade:
    #: Packages sold, by day: every sale on their ledger, bot or panel.
    sales: TimeSeries
    #: What those sales cost them, in toman: their wholesale price.
    cost: TimeSeries
    #: What their customers paid in their bot, in toman: their retail price.
    #: Sales made by hand from the panel were paid outside, so are not here.
    revenue: TimeSeries
    #: Their best-selling packages in the period, by count.
    top_plans: tuple[BreakdownSlice, ...]
    #: Customers who first started their bot in the period.
    new_customers: int
    #: Every customer their bot has.
    customers: int
    #: Their customers' services running now.
    active_services: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "sales": self.sales.as_dict(),
            "cost": self.cost.as_dict(),
            "revenue": self.revenue.as_dict(),
            "topPlans": [plan.as_dict() for plan in self.top_plans],
            "newCustomers": self.new_customers,
            "customers": self.customers,
            "activeServices": self.active_services,
        }


@dataclass(frozen=True, slots=True)
class ResellerTotals:
    """All-time sums off their ledger, for the portal's four cards.

    Summed by the database. They were summed over the last 500 ledger rows,
    so a reseller past their 500th sale saw totals that stopped growing.
    """

    sales: int
    spent: int
    topped_up: int

    @property
    def average_sale(self) -> int:
        return self.spent // self.sales if self.sales else 0


class ResellerTradeReader(Protocol):
    async def trade(self, reseller_id: uuid.UUID, period: DateRange) -> ResellerTrade: ...

    async def totals(self, reseller_id: uuid.UUID) -> ResellerTotals: ...
