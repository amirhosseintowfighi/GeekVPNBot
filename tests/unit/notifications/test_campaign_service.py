"""Campaign announcements."""

from __future__ import annotations

from geekvpn.domain.notifications.enums import JobKind
from geekvpn.domain.notifications.events import ReminderJobCompleted
from tests.unit.notifications.fakes import EPOCH, USER_ID, campaign
from tests.unit.notifications.world import World


def test_announcing_reaches_the_audience():
    w = World()
    w.audience.ids = [1, 2, 3]
    result = w.campaigns.announce(campaign(now=EPOCH))
    assert result.recipients == 3
    assert result.queued == 3
    assert w.stored()[0].message.key == "campaign.launched"


def test_the_discount_is_written_in_persian_digits():
    w = World()
    w.audience.ids = [USER_ID]
    w.campaigns.announce(campaign(percent=30, now=EPOCH))
    body = w.only().message.body_fa
    assert "\u06f3\u06f0" in body
    assert "30" not in body


def test_announcing_twice_notifies_once():
    w = World()
    w.audience.ids = [USER_ID]
    snapshot = campaign(now=EPOCH)
    w.campaigns.announce(snapshot)
    second = w.campaigns.announce(snapshot)
    assert second.queued == 0
    assert second.skipped == 1
    assert len(w.stored()) == 1


def test_a_campaign_is_marked_announced_even_if_everyone_muted_promos():
    """Otherwise the job retries this campaign forever."""
    w = World()
    w.audience.ids = [USER_ID]
    w.mute("promos")
    result = w.campaigns.announce(campaign(now=EPOCH))
    assert result.queued == 0
    assert w.campaign_reader.announced == ["cmp-1"]


def test_promos_are_mutable_unlike_transactional_messages():
    w = World()
    w.audience.ids = [USER_ID]
    w.mute("promos")
    w.campaigns.announce(campaign(now=EPOCH))
    assert w.stored() == []


def test_pending_run_skips_a_campaign_that_has_not_started():
    """A limited-time offer for something unbuyable costs trust."""
    w = World()
    w.audience.ids = [USER_ID]
    w.campaign_reader.campaigns = [campaign(live=False, now=EPOCH)]
    assert w.campaigns.run_pending_announcements() == []
    assert w.campaign_reader.announced == []


def test_pending_run_announces_a_live_campaign():
    w = World()
    w.audience.ids = [USER_ID]
    w.campaign_reader.campaigns = [campaign(live=True, now=EPOCH)]
    results = w.campaigns.run_pending_announcements()
    assert len(results) == 1
    assert w.campaign_reader.announced == ["cmp-1"]


def test_already_announced_campaigns_are_not_reconsidered():
    w = World()
    w.campaign_reader.campaigns = [campaign(announced=True, now=EPOCH)]
    assert w.campaigns.run_pending_announcements() == []


def test_the_job_reports_itself():
    w = World()
    w.audience.ids = [USER_ID]
    w.campaign_reader.campaigns = [campaign(now=EPOCH)]
    w.campaigns.run_pending_announcements()
    events = w.events.of_type(ReminderJobCompleted)
    assert events[-1].job is JobKind.CAMPAIGN_ANNOUNCE


def test_marketing_cap_limits_a_burst_of_campaigns():
    w = World()
    w.audience.ids = [USER_ID]
    for index in range(4):
        w.campaigns.announce(campaign(campaign_id=f"cmp-{index}", now=EPOCH))
    assert len(w.stored()) == 2
