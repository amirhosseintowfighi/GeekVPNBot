"""Campaign announcements.

A campaign already exists in the catalogue with its discount and its window;
this service only decides who hears about it and makes sure they hear once.

It is deliberately thin over the broadcast machinery rather than a parallel
implementation: the same batching, the same dedupe, the same preference rules.
The difference is that campaign copy comes from the catalogue template so the
Persian stays consistent, and that PROMOS is a mutable category -- a customer
who switched off promotions hears nothing, which is the whole point of the
switch.
"""

from __future__ import annotations

from dataclasses import dataclass

from geekvpn.application.notifications.engine import NotificationEngine
from geekvpn.application.notifications.ports import (
    AudienceResolver,
    CampaignReader,
    CampaignSnapshot,
    Clock,
    EventPublisher,
)
from geekvpn.domain.notifications.enums import JobKind
from geekvpn.domain.notifications.events import ReminderJobCompleted
from geekvpn.domain.notifications.schedule import campaign_dedupe_key


@dataclass(frozen=True, slots=True)
class CampaignAnnouncement:
    campaign_id: str
    recipients: int
    queued: int
    skipped: int


class CampaignService:
    """Announce live campaigns to their audience, exactly once each."""

    def __init__(
        self,
        *,
        engine: NotificationEngine,
        campaigns: CampaignReader,
        audiences: AudienceResolver,
        clock: Clock,
        events: EventPublisher,
    ) -> None:
        self._engine = engine
        self._campaigns = campaigns
        self._audiences = audiences
        self._clock = clock
        self._events = events

    def announce(self, campaign: CampaignSnapshot) -> CampaignAnnouncement:
        """Tell the campaign's audience about it.

        The campaign is marked announced even when every recipient had
        promotions muted. Re-running would not reach them either, and leaving
        it unannounced would make the job retry forever.
        """
        recipients = self._audiences.resolve(campaign.audience, reference=campaign.audience_ref)
        queued = skipped = 0

        for user_id in recipients:
            result = self._engine.notify(
                user_id=user_id,
                template_key="campaign.launched",
                fields={
                    "title": campaign.title_fa,
                    "percent": campaign.discount_percent,
                },
                dedupe_key=campaign_dedupe_key(campaign.campaign_id, user_id),
                source=f"campaign:{campaign.campaign_id}",
            )
            if result.was_queued:
                queued += 1
            else:
                skipped += 1

        self._campaigns.mark_announced(campaign.campaign_id, now=self._clock.now())

        return CampaignAnnouncement(
            campaign_id=campaign.campaign_id,
            recipients=len(recipients),
            queued=queued,
            skipped=skipped,
        )

    def run_pending_announcements(self) -> list[CampaignAnnouncement]:
        """Announce every live, not-yet-announced campaign.

        A campaign whose window has not opened yet is left alone rather than
        announced early -- "limited time offer" for something not yet buyable
        is how a shop loses trust.
        """
        now = self._clock.now()
        results: list[CampaignAnnouncement] = []

        for campaign in self._campaigns.unannounced(now=now):
            if not campaign.is_live(now):
                continue
            results.append(self.announce(campaign))

        self._events.publish_all(
            [
                ReminderJobCompleted(
                    job=JobKind.CAMPAIGN_ANNOUNCE,
                    examined=len(results),
                    queued=sum(r.queued for r in results),
                    skipped=sum(r.skipped for r in results),
                )
            ]
        )
        return results


__all__ = ["CampaignAnnouncement", "CampaignService"]
