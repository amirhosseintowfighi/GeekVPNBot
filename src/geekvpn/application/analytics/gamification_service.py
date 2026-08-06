"""Player profiles and leaderboards.

Profiles are recomputed from a customer snapshot on every read. Nothing is
stored, so a refunded order silently corrects the points instead of leaving a
phantom badge behind forever.

The leaderboard shows display names, never Telegram handles or user ids: a
public ranking that leaks who bought a VPN is a safety problem, not a feature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from geekvpn.application.analytics.ports import AnalyticsReaders, Clock
from geekvpn.domain.analytics.calendar import fa_digits
from geekvpn.domain.analytics.gamification import (
    Badge,
    PlayerProfile,
    earned_badges,
    points_for,
)
from geekvpn.domain.analytics.referral import ReferrerStanding, leaderboard
from geekvpn.domain.analytics.timeframe import DateRange

LEADERBOARD_SIZE = 10
LEADERBOARD_DAYS = 30


@dataclass(frozen=True, slots=True)
class LeaderboardRow:
    """One public ranking row."""

    rank: int
    display_name: str
    converted: int
    points: int

    def rank_fa(self) -> str:
        return fa_digits(self.rank)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "rankFa": self.rank_fa(),
            "displayName": self.display_name,
            "converted": self.converted,
            "points": self.points,
        }


class GamificationService:
    def __init__(self, *, readers: AnalyticsReaders, clock: Clock) -> None:
        self._readers = readers
        self._clock = clock

    def profile(self, user_id: int) -> PlayerProfile | None:
        now = self._clock.now()
        snapshot = self._readers.customers.snapshot_for(user_id, now=now)
        if snapshot is None:
            return None
        return PlayerProfile.build(snapshot, now=now)

    def badges(self, user_id: int) -> tuple[Badge, ...]:
        profile = self.profile(user_id)
        return profile.badges if profile else ()

    def points(self, user_id: int) -> int:
        now = self._clock.now()
        snapshot = self._readers.customers.snapshot_for(user_id, now=now)
        if snapshot is None:
            return 0
        return points_for(snapshot, badges=len(earned_badges(snapshot)))

    def leaderboard(
        self, *, days: int = LEADERBOARD_DAYS, limit: int = LEADERBOARD_SIZE
    ) -> tuple[LeaderboardRow, ...]:
        range = DateRange.calendar_days(days, now=self._clock.now())
        standings: tuple[ReferrerStanding, ...] = tuple(
            self._readers.referral.standings(range, limit=limit * 2)
        )
        ranked = leaderboard(standings, limit=limit)
        return tuple(
            LeaderboardRow(
                rank=index + 1,
                display_name=item.display_name,
                converted=item.converted,
                points=item.converted * 25,
            )
            for index, item in enumerate(ranked)
        )


__all__ = [
    "LEADERBOARD_DAYS",
    "LEADERBOARD_SIZE",
    "GamificationService",
    "LeaderboardRow",
]
