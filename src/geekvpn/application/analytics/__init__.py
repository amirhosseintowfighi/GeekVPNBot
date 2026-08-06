"""Analytics application layer.

Services here fetch aggregated numbers through ports and hand them to the
analytics domain. They hold no arithmetic of their own, so the admin screen,
the CSV export and any future digest all quote the same figures.
"""

from geekvpn.application.analytics.analytics_service import (
    COHORT_MONTHS,
    DEFAULT_DAYS,
    PAYMENT_METHOD_LABELS_FA,
    AnalyticsService,
)
from geekvpn.application.analytics.dashboard_service import (
    DASHBOARD_DAYS,
    DashboardService,
)
from geekvpn.application.analytics.export import (
    CONTENT_TYPE,
    bundle_csv,
    filename_for,
    metrics_csv,
    series_csv,
)
from geekvpn.application.analytics.gamification_service import (
    LEADERBOARD_DAYS,
    LEADERBOARD_SIZE,
    GamificationService,
    LeaderboardRow,
)
from geekvpn.application.analytics.marketing import (
    MIN_AUDIENCE_FOR_CAMPAIGN,
    WEAK_CAMPAIGN_RETURN_PERCENT,
    MarketingService,
    Suggestion,
)
from geekvpn.application.analytics.ports import (
    AnalyticsReaders,
    CampaignAnalyticsReader,
    Clock,
    CustomerReader,
    FunnelReader,
    NodeReader,
    ReferralReader,
    ReportCache,
    RetentionReader,
    RevenueReader,
    WorkQueue,
    WorkQueueReader,
)
from geekvpn.application.analytics.segmentation_service import (
    MAX_AUDIENCE,
    Audience,
    SegmentationService,
)

__all__ = [
    "COHORT_MONTHS",
    "CONTENT_TYPE",
    "DASHBOARD_DAYS",
    "DEFAULT_DAYS",
    "LEADERBOARD_DAYS",
    "LEADERBOARD_SIZE",
    "MAX_AUDIENCE",
    "MIN_AUDIENCE_FOR_CAMPAIGN",
    "PAYMENT_METHOD_LABELS_FA",
    "WEAK_CAMPAIGN_RETURN_PERCENT",
    "AnalyticsReaders",
    "AnalyticsService",
    "Audience",
    "CampaignAnalyticsReader",
    "Clock",
    "CustomerReader",
    "DashboardService",
    "FunnelReader",
    "GamificationService",
    "LeaderboardRow",
    "MarketingService",
    "NodeReader",
    "ReferralReader",
    "ReportCache",
    "RetentionReader",
    "RevenueReader",
    "SegmentationService",
    "Suggestion",
    "WorkQueue",
    "WorkQueueReader",
    "bundle_csv",
    "filename_for",
    "metrics_csv",
    "series_csv",
]
