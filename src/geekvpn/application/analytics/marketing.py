"""Marketing tools: what to offer, to whom, and whether it worked.

Suggestions are advice, never actions. The service returns a recommendation
with the numbers behind it and a human decides; auto-firing discount
campaigns at customers based on a heuristic is how a business trains people
to wait for the next sale instead of paying full price.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from geekvpn.application.analytics.ports import AnalyticsReaders, Clock
from geekvpn.application.analytics.segmentation_service import SegmentationService
from geekvpn.domain.analytics.calendar import fa_digits
from geekvpn.domain.analytics.enums import SegmentKind
from geekvpn.domain.analytics.funnel import Funnel
from geekvpn.domain.analytics.referral import CampaignPerformance
from geekvpn.domain.analytics.timeframe import DateRange

MIN_AUDIENCE_FOR_CAMPAIGN = 20
WEAK_CAMPAIGN_RETURN_PERCENT = 150.0
"""Below this, a campaign gave away more than it plausibly earned back."""

SUGGESTED_WINBACK_PERCENT = 20
SUGGESTED_EXPIRING_PERCENT = 10


@dataclass(frozen=True, slots=True)
class Suggestion:
    """One recommended marketing move."""

    key: str
    title_fa: str
    detail_fa: str
    segment: SegmentKind | None = None
    audience_size: int = 0
    discount_percent: int = 0
    priority: int = 0
    """Higher runs first. Derived from money at stake, not from opinion."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "titleFa": self.title_fa,
            "detailFa": self.detail_fa,
            "segment": str(self.segment) if self.segment else None,
            "audienceSize": self.audience_size,
            "discountPercent": self.discount_percent,
            "priority": self.priority,
        }


class MarketingService:
    def __init__(
        self,
        *,
        readers: AnalyticsReaders,
        segmentation: SegmentationService,
        clock: Clock,
    ) -> None:
        self._readers = readers
        self._segments = segmentation
        self._clock = clock

    # ---- Suggestions ----------------------------------------------------

    def suggestions(self, *, days: int = 30) -> tuple[Suggestion, ...]:
        range = DateRange.calendar_days(days, now=self._clock.now())
        found: list[Suggestion] = []
        found.extend(self._audience_suggestions())
        found.extend(self._funnel_suggestions(range))
        found.extend(self._campaign_suggestions(range))
        found.extend(self._referral_suggestions(range))
        return tuple(sorted(found, key=lambda item: item.priority, reverse=True))

    def _audience_suggestions(self) -> list[Suggestion]:
        out: list[Suggestion] = []
        report = self._segments.report()

        for kind, percent in (
            (SegmentKind.EXPIRING_SOON, SUGGESTED_EXPIRING_PERCENT),
            (SegmentKind.EXPIRED, SUGGESTED_WINBACK_PERCENT),
            (SegmentKind.CHURNED, SUGGESTED_WINBACK_PERCENT),
        ):
            stat = report.stat_for(kind)
            if stat.customers < MIN_AUDIENCE_FOR_CAMPAIGN:
                continue
            out.append(
                Suggestion(
                    key=f"target_{kind}",
                    title_fa=(
                        f"\u067e\u06cc\u0634\u0646\u0647\u0627\u062f \u0628\u0647 {stat.label_fa}"
                    ),
                    detail_fa=(
                        f"{fa_digits(stat.customers)} \u0645\u0634\u062a\u0631\u06cc "
                        "\u0648\u0627\u062c\u062f \u0634\u0631\u0627\u06cc\u0637 "
                        f"\u062a\u062e\u0641\u06cc\u0641 {fa_digits(percent)}\u066a "
                        "\u0647\u0633\u062a\u0646\u062f."
                    ),
                    segment=kind,
                    audience_size=stat.customers,
                    discount_percent=percent,
                    priority=stat.customers,
                )
            )
        return out

    def _funnel_suggestions(self, range: DateRange) -> list[Suggestion]:
        funnel = Funnel.build(self._readers.funnel.stage_counts(range))
        if not funnel.needs_attention():
            return []
        leak = funnel.worst_leak()
        if leak is None:
            return []
        return [
            Suggestion(
                key="funnel_leak",
                title_fa=(
                    "\u0631\u06cc\u0632\u0634 \u062f\u0631 \u0645\u0631\u062d\u0644\u0647\u0654 "
                    f"{leak.label_fa}"
                ),
                detail_fa=(
                    f"{fa_digits(leak.dropped)} \u0646\u0641\u0631 "
                    f"({fa_digits(round(leak.drop_rate))}\u066a) "
                    "\u062f\u0631 \u0627\u06cc\u0646 \u0645\u0631\u062d\u0644\u0647 "
                    "\u0631\u0647\u0627 \u06a9\u0631\u062f\u0646\u062f."
                ),
                priority=leak.dropped,
            )
        ]

    def _campaign_suggestions(self, range: DateRange) -> list[Suggestion]:
        out: list[Suggestion] = []
        for campaign in self._readers.campaigns.performance(range):
            if campaign.discount_given <= 0:
                continue
            if campaign.return_on_discount() >= WEAK_CAMPAIGN_RETURN_PERCENT:
                continue
            out.append(
                Suggestion(
                    key=f"weak_campaign_{campaign.campaign_id}",
                    title_fa=(
                        "\u06a9\u0645\u067e\u06cc\u0646 \u06a9\u0645\u200c\u0628\u0627\u0632\u062f\u0647: "
                        f"{campaign.name_fa}"
                    ),
                    detail_fa=(
                        "\u0628\u0627\u0632\u06af\u0634\u062a "
                        f"{fa_digits(round(campaign.return_on_discount()))}\u066a "
                        "\u0646\u0633\u0628\u062a \u0628\u0647 \u062a\u062e\u0641\u06cc\u0641 "
                        "\u062f\u0627\u062f\u0647\u200c\u0634\u062f\u0647."
                    ),
                    priority=campaign.discount_given // 100_000,
                )
            )
        return out

    def _referral_suggestions(self, range: DateRange) -> list[Suggestion]:
        performance = self._readers.referral.performance(range)
        if performance.is_profitable() or performance.total_cost == 0:
            return []
        return [
            Suggestion(
                key="referral_unprofitable",
                title_fa="\u0628\u0631\u0646\u0627\u0645\u0647\u0654 \u0645\u0639\u0631\u0641\u06cc \u0632\u06cc\u0627\u0646\u200c\u062f\u0647 \u0627\u0633\u062a",
                detail_fa=(
                    "\u0647\u0632\u06cc\u0646\u0647\u0654 \u067e\u0627\u062f\u0627\u0634 "
                    "\u0627\u0632 \u062f\u0631\u0622\u0645\u062f \u062d\u0627\u0635\u0644 "
                    "\u0628\u06cc\u0634\u062a\u0631 \u0634\u062f\u0647 \u0627\u0633\u062a."
                ),
                priority=1,
            )
        ]

    # ---- Campaign review ------------------------------------------------

    def campaign_ranking(self, *, days: int = 90) -> tuple[CampaignPerformance, ...]:
        """Best first, judged on net revenue rather than redemptions."""
        range = DateRange.calendar_days(days, now=self._clock.now())
        rows = self._readers.campaigns.performance(range)
        return tuple(sorted(rows, key=lambda item: item.net_revenue, reverse=True))

    def underperformers(self, *, days: int = 90) -> tuple[CampaignPerformance, ...]:
        return tuple(
            item
            for item in self.campaign_ranking(days=days)
            if item.discount_given > 0 and item.return_on_discount() < WEAK_CAMPAIGN_RETURN_PERCENT
        )


__all__ = [
    "MIN_AUDIENCE_FOR_CAMPAIGN",
    "SUGGESTED_EXPIRING_PERCENT",
    "SUGGESTED_WINBACK_PERCENT",
    "WEAK_CAMPAIGN_RETURN_PERCENT",
    "MarketingService",
    "Suggestion",
]
