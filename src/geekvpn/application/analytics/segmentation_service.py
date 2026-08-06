"""Turning segments into audiences.

This is the bridge between analytics and the notification engine. Phase 10's
broadcast service asks an ``AudienceResolver`` for user ids; this service is
that resolver, backed by segment rules instead of a hand-kept list.

Rules are evaluated fresh on every call. A saved audience would keep mailing
a win-back discount to someone who renewed an hour after the list was built.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from geekvpn.application.analytics.ports import Clock, CustomerReader
from geekvpn.domain.analytics.enums import SegmentKind
from geekvpn.domain.analytics.segmentation import (
    CustomerSnapshot,
    SegmentReport,
    SegmentStat,
    classify,
    matches,
)

MAX_AUDIENCE = 50_000


@dataclass(frozen=True, slots=True)
class Audience:
    """A resolved target list, with the rule that produced it."""

    kind: SegmentKind
    user_ids: tuple[int, ...]
    resolved_at: datetime

    @property
    def size(self) -> int:
        return len(self.user_ids)

    @property
    def label_fa(self) -> str:
        return self.kind.label_fa()

    def is_empty(self) -> bool:
        return not self.user_ids


class SegmentationService:
    def __init__(self, *, customers: CustomerReader, clock: Clock) -> None:
        self._customers = customers
        self._clock = clock

    def _snapshots(self) -> tuple[CustomerSnapshot, ...]:
        return tuple(self._customers.snapshots(now=self._clock.now()))

    def report(self) -> SegmentReport:
        return SegmentReport.build(self._snapshots())

    def stat(self, kind: SegmentKind) -> SegmentStat:
        return self.report().stat_for(kind)

    def audience(self, kind: SegmentKind, *, limit: int = MAX_AUDIENCE) -> Audience:
        """Everyone matching a segment, capped.

        Uses ``matches`` rather than ``classify`` so overlapping targeting
        works: a whale who happens to be expiring is still a whale.
        """
        now = self._clock.now()
        ids = tuple(snapshot.user_id for snapshot in self._snapshots() if matches(snapshot, kind))[
            :limit
        ]
        return Audience(kind=kind, user_ids=ids, resolved_at=now)

    def audience_size(self, kind: SegmentKind) -> int:
        return self.audience(kind).size

    def segment_of(self, user_id: int) -> SegmentKind | None:
        snapshot = self._customers.snapshot_for(user_id, now=self._clock.now())
        return classify(snapshot) if snapshot else None

    def win_back_audience(self, *, limit: int = MAX_AUDIENCE) -> Audience:
        """Everyone worth a discount, as one list.

        Deduplicated across the four win-back segments -- a churned customer
        must not receive the same offer twice because two rules matched.
        """
        now = self._clock.now()
        seen: list[int] = []
        known: set[int] = set()
        for snapshot in self._snapshots():
            if not classify(snapshot).is_win_back():
                continue
            if snapshot.user_id in known:
                continue
            known.add(snapshot.user_id)
            seen.append(snapshot.user_id)
            if len(seen) >= limit:
                break
        return Audience(kind=SegmentKind.CHURNED, user_ids=tuple(seen), resolved_at=now)


__all__ = ["MAX_AUDIENCE", "Audience", "SegmentationService"]
