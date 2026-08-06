"""What analytics needs from the outside world.

Every reader returns already-aggregated numbers. The alternative -- handing
analytics a repository and letting it sum rows in Python -- would pull the
whole orders table into memory once per page load. Aggregation belongs in the
query, so the port speaks in totals.

All readers are synchronous. These calls sit behind a cache and run against
indexed aggregates; making them async would infect every caller for no gain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from geekvpn.domain.analytics.enums import FunnelStage
from geekvpn.domain.analytics.nodes import NodeUsage
from geekvpn.domain.analytics.referral import (
    CampaignPerformance,
    ReferralPerformance,
    ReferrerStanding,
)
from geekvpn.domain.analytics.retention import Cohort, RetentionSummary
from geekvpn.domain.analytics.revenue import PlanSales, RevenueTotals, TrafficSold
from geekvpn.domain.analytics.segmentation import CustomerSnapshot
from geekvpn.domain.analytics.timeframe import DateRange


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class RevenueReader(Protocol):
    """Money, in whole Toman."""

    def totals(self, range: DateRange) -> RevenueTotals: ...

    def net_revenue_by_bucket(self, range: DateRange) -> dict[datetime, float]:
        """Keyed by bucket start, as produced by ``DateRange.buckets()``."""
        ...

    def orders_by_bucket(self, range: DateRange) -> dict[datetime, float]: ...

    def plan_sales(self, range: DateRange) -> list[PlanSales]: ...

    def revenue_by_method(self, range: DateRange) -> dict[str, float]:
        """Keyed by payment method value, e.g. ``card`` or ``wallet``."""
        ...

    def traffic_sold(self, range: DateRange) -> TrafficSold: ...


@runtime_checkable
class FunnelReader(Protocol):
    def stage_counts(self, range: DateRange) -> dict[FunnelStage, int]: ...


@runtime_checkable
class RetentionReader(Protocol):
    def summary(self, range: DateRange) -> RetentionSummary: ...

    def cohorts(self, *, months: int, now: datetime) -> list[Cohort]: ...


@runtime_checkable
class ReferralReader(Protocol):
    def performance(self, range: DateRange) -> ReferralPerformance: ...

    def standings(self, range: DateRange, *, limit: int = 10) -> list[ReferrerStanding]: ...


@runtime_checkable
class CampaignAnalyticsReader(Protocol):
    def performance(self, range: DateRange) -> list[CampaignPerformance]: ...


@runtime_checkable
class NodeReader(Protocol):
    def usage(self, range: DateRange) -> list[NodeUsage]: ...


@runtime_checkable
class CustomerReader(Protocol):
    """Flat snapshots for segmentation and gamification."""

    def snapshots(self, *, now: datetime, limit: int = 50_000) -> list[CustomerSnapshot]: ...

    def snapshot_for(self, user_id: int, *, now: datetime) -> CustomerSnapshot | None: ...


@dataclass(frozen=True, slots=True)
class WorkQueue:
    """What is waiting for a human right now.

    Not derived from the date range: a receipt from last week that nobody
    reviewed is today's problem.
    """

    pending_payments: int = 0
    open_tickets: int = 0
    overdue_tickets: int = 0
    failed_provisions: int = 0
    expiring_today: int = 0

    def total(self) -> int:
        return self.pending_payments + self.open_tickets + self.failed_provisions


@runtime_checkable
class WorkQueueReader(Protocol):
    def pending(self, *, now: datetime) -> WorkQueue: ...


@runtime_checkable
class ReportCache(Protocol):
    """Optional. Analytics is correct without it, just slower."""

    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str, *, ttl_seconds: int) -> None: ...


@dataclass(frozen=True, slots=True)
class AnalyticsReaders:
    """One bag of readers so services take a single dependency."""

    revenue: RevenueReader
    funnel: FunnelReader
    retention: RetentionReader
    referral: ReferralReader
    campaigns: CampaignAnalyticsReader
    nodes: NodeReader
    customers: CustomerReader
    work_queue: WorkQueueReader | None = None


__all__ = [
    "AnalyticsReaders",
    "CampaignAnalyticsReader",
    "Clock",
    "CustomerReader",
    "FunnelReader",
    "NodeReader",
    "ReferralReader",
    "ReportCache",
    "RetentionReader",
    "RevenueReader",
    "WorkQueue",
    "WorkQueueReader",
]
