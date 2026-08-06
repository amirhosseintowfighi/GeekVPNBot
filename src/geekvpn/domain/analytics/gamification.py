"""Badges, points and streaks.

Deliberately cosmetic. Points buy nothing and expire never: the moment a
badge becomes spendable it is money, and money belongs in the payments
context with an audit trail, not in a motivational widget.

Awarding is a pure function of a customer snapshot, so a badge can never be
lost by replaying events and can be recomputed after a data fix.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from geekvpn.domain.analytics.calendar import fa_digits
from geekvpn.domain.analytics.enums import BadgeKind
from geekvpn.domain.analytics.segmentation import CustomerSnapshot

POINTS_PER_ORDER = 10
POINTS_PER_100K_TOMAN = 1
POINTS_PER_REFERRAL = 25
POINTS_PER_BADGE = 15

BIG_SPENDER_TOMAN = 5_000_000
REFERRER_PRO_CONVERSIONS = 5
EARLY_ADOPTER_JOINED_DAYS = 180
HALF_YEAR_DAYS = 180
FULL_YEAR_DAYS = 365

LEVEL_THRESHOLDS: tuple[int, ...] = (0, 50, 150, 400, 900)
LEVEL_LABELS_FA: tuple[str, ...] = (
    "\u062a\u0627\u0632\u0647\u200c\u06a9\u0627\u0631",
    "\u0647\u0645\u0631\u0627\u0647",
    "\u062d\u0631\u0641\u0647\u200c\u0627\u06cc",
    "\u0642\u0647\u0631\u0645\u0627\u0646",
    "\u0627\u0641\u0633\u0627\u0646\u0647",
)


@dataclass(frozen=True, slots=True)
class Badge:
    """An earned badge, ready to render."""

    kind: BadgeKind
    earned_at: datetime | None = None

    @property
    def label_fa(self) -> str:
        return self.kind.label_fa()

    @property
    def emoji(self) -> str:
        return self.kind.emoji()

    def title_fa(self) -> str:
        return f"{self.emoji} {self.label_fa}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": str(self.kind),
            "labelFa": self.label_fa,
            "emoji": self.emoji,
            "earnedAt": self.earned_at.isoformat() if self.earned_at else None,
        }


def earned_badges(snapshot: CustomerSnapshot, *, now: datetime | None = None) -> tuple[Badge, ...]:
    """Every badge this customer currently qualifies for, in display order."""
    earned: list[BadgeKind] = []

    if snapshot.orders >= 1:
        earned.append(BadgeKind.FIRST_PURCHASE)
    if snapshot.orders >= 4:
        earned.append(BadgeKind.RENEWED_THRICE)
    if snapshot.joined_days_ago >= HALF_YEAR_DAYS:
        earned.append(BadgeKind.HALF_YEAR)
    if snapshot.joined_days_ago >= FULL_YEAR_DAYS:
        earned.append(BadgeKind.FULL_YEAR)
    if snapshot.lifetime_spend >= BIG_SPENDER_TOMAN:
        earned.append(BadgeKind.BIG_SPENDER)
    if snapshot.referrals_converted >= 1:
        earned.append(BadgeKind.REFERRER_ROOKIE)
    if snapshot.referrals_converted >= REFERRER_PRO_CONVERSIONS:
        earned.append(BadgeKind.REFERRER_PRO)
    if snapshot.joined_days_ago >= EARLY_ADOPTER_JOINED_DAYS and snapshot.orders >= 1:
        earned.append(BadgeKind.EARLY_ADOPTER)

    return tuple(Badge(kind=kind, earned_at=now) for kind in earned)


def points_for(snapshot: CustomerSnapshot, *, badges: int | None = None) -> int:
    """Points are derived, never stored.

    Storing a running total means a refund or a corrected order silently
    leaves the balance wrong forever.
    """
    badge_count = len(earned_badges(snapshot)) if badges is None else badges
    return (
        snapshot.orders * POINTS_PER_ORDER
        + (snapshot.lifetime_spend // 100_000) * POINTS_PER_100K_TOMAN
        + snapshot.referrals_converted * POINTS_PER_REFERRAL
        + badge_count * POINTS_PER_BADGE
    )


def level_for(points: int) -> int:
    """Zero-based level index."""
    level = 0
    for index, threshold in enumerate(LEVEL_THRESHOLDS):
        if points >= threshold:
            level = index
    return level


def level_label_fa(points: int) -> str:
    return LEVEL_LABELS_FA[level_for(points)]


def points_to_next_level(points: int) -> int | None:
    """None at the top level -- there is nothing left to chase."""
    level = level_for(points)
    if level >= len(LEVEL_THRESHOLDS) - 1:
        return None
    return LEVEL_THRESHOLDS[level + 1] - points


@dataclass(frozen=True, slots=True)
class PlayerProfile:
    """The gamification card shown in the Mini App."""

    user_id: int
    points: int
    level: int
    level_label_fa: str
    badges: tuple[Badge, ...] = ()
    to_next_level: int | None = None

    @classmethod
    def build(cls, snapshot: CustomerSnapshot, *, now: datetime | None = None) -> PlayerProfile:
        badges = earned_badges(snapshot, now=now)
        points = points_for(snapshot, badges=len(badges))
        return cls(
            user_id=snapshot.user_id,
            points=points,
            level=level_for(points),
            level_label_fa=level_label_fa(points),
            badges=badges,
            to_next_level=points_to_next_level(points),
        )

    def progress_percent(self) -> float:
        """Progress through the current level, 100 at the top."""
        if self.to_next_level is None:
            return 100.0
        floor = LEVEL_THRESHOLDS[self.level]
        ceiling = LEVEL_THRESHOLDS[self.level + 1]
        span = ceiling - floor
        return ((self.points - floor) / span * 100.0) if span else 0.0

    def summary_fa(self) -> str:
        return (
            f"{self.level_label_fa} \u00b7 "
            f"{fa_digits(self.points)} \u0627\u0645\u062a\u06cc\u0627\u0632"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "userId": self.user_id,
            "points": self.points,
            "level": self.level,
            "levelLabelFa": self.level_label_fa,
            "toNextLevel": self.to_next_level,
            "progressPercent": self.progress_percent(),
            "summaryFa": self.summary_fa(),
            "badges": [badge.as_dict() for badge in self.badges],
        }


__all__ = [
    "LEVEL_LABELS_FA",
    "LEVEL_THRESHOLDS",
    "POINTS_PER_ORDER",
    "POINTS_PER_REFERRAL",
    "Badge",
    "PlayerProfile",
    "earned_badges",
    "level_for",
    "level_label_fa",
    "points_for",
    "points_to_next_level",
]
