"""The operator landing screen.

A queue, not a report. Everything here is something a human can act on in the
next ten minutes, which is why the counts come from a separate work-queue
reader rather than from the date-ranged analytics readers: an unreviewed
receipt from nine days ago is still waiting today.
"""

from __future__ import annotations

from geekvpn.application.analytics.ports import AnalyticsReaders, Clock, WorkQueue
from geekvpn.domain.analytics.dashboard import ActionItem, OperatorDashboard
from geekvpn.domain.analytics.enums import Granularity, MetricFormat, MetricKey
from geekvpn.domain.analytics.metrics import MetricCard
from geekvpn.domain.analytics.nodes import FleetUsage
from geekvpn.domain.analytics.series import TimeSeries
from geekvpn.domain.analytics.timeframe import DateRange

DASHBOARD_DAYS = 14

HREF_PAYMENTS = "/wallet"
HREF_TICKETS = "/tickets"
HREF_ORDERS = "/orders"
HREF_SERVERS = "/servers"


class DashboardService:
    def __init__(self, *, readers: AnalyticsReaders, clock: Clock) -> None:
        self._readers = readers
        self._clock = clock

    def build(self) -> OperatorDashboard:
        now = self._clock.now()
        range = DateRange.calendar_days(DASHBOARD_DAYS, now=now)
        readers = self._readers

        revenue = readers.revenue.totals(range)
        before = readers.revenue.totals(range.previous())
        queue = (
            readers.work_queue.pending(now=now) if readers.work_queue is not None else WorkQueue()
        )
        fleet = FleetUsage(nodes=tuple(readers.nodes.usage(range)))

        return OperatorDashboard(
            metrics=(
                MetricCard.of(MetricKey.NET_REVENUE, revenue.net, previous=before.net),
                MetricCard.of(MetricKey.ORDERS, revenue.orders, previous=before.orders),
                MetricCard.of(MetricKey.NEW_USERS, revenue.new_users, previous=before.new_users),
                MetricCard.of(MetricKey.ACTIVE_SUBSCRIPTIONS, float(queue.expiring_today)),
            ),
            actions=self._actions(queue, fleet),
            revenue_series=TimeSeries.build(
                key="net_revenue",
                label_fa=MetricKey.NET_REVENUE.label_fa(),
                format=MetricFormat.TOMAN,
                range=range,
                values=readers.revenue.net_revenue_by_bucket(range),
                granularity=Granularity.DAY,
            ),
            fleet=fleet,
        )

    def _actions(self, queue: WorkQueue, fleet: FleetUsage) -> tuple[ActionItem, ...]:
        """Only non-zero rows survive; a queue of zeros is wallpaper."""
        offline = sum(1 for node in fleet.nodes if not node.online)
        candidates = (
            ActionItem(
                key="pending_payments",
                label_fa="\u0631\u0633\u06cc\u062f \u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 \u0628\u0631\u0631\u0633\u06cc",
                count=queue.pending_payments,
                href=HREF_PAYMENTS,
                urgent=True,
            ),
            ActionItem(
                key="failed_provisions",
                label_fa="\u0633\u0631\u0648\u06cc\u0633 \u062a\u062d\u0648\u06cc\u0644\u200c\u0646\u0634\u062f\u0647",
                count=queue.failed_provisions,
                href=HREF_ORDERS,
                urgent=True,
            ),
            ActionItem(
                key="overdue_tickets",
                label_fa="\u062a\u06cc\u06a9\u062a \u062e\u0627\u0631\u062c \u0627\u0632 \u0645\u0647\u0644\u062a \u067e\u0627\u0633\u062e",
                count=queue.overdue_tickets,
                href=HREF_TICKETS,
                urgent=True,
            ),
            ActionItem(
                key="open_tickets",
                label_fa="\u062a\u06cc\u06a9\u062a \u0628\u0627\u0632",
                count=queue.open_tickets,
                href=HREF_TICKETS,
            ),
            ActionItem(
                key="offline_nodes",
                label_fa="\u0633\u0631\u0648\u0631 \u0622\u0641\u0644\u0627\u06cc\u0646",
                count=offline,
                href=HREF_SERVERS,
                urgent=True,
            ),
        )
        return tuple(item for item in candidates if item.count > 0)


__all__ = ["DASHBOARD_DAYS", "DashboardService"]
