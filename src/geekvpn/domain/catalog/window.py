"""A scheduling window shared by coupons and campaigns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from geekvpn.domain.catalog.errors import CatalogValidationError


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """An optionally open-ended interval, always in aware UTC.

    Naive datetimes are rejected outright rather than assumed to be UTC.
    Iranian operators schedule flash sales in local time; a naive value that
    silently means UTC is a sale that starts three and a half hours late.
    """

    starts_at: datetime | None = None
    ends_at: datetime | None = None

    def __post_init__(self) -> None:
        for label, value in (("starts_at", self.starts_at), ("ends_at", self.ends_at)):
            if value is not None and value.tzinfo is None:
                raise CatalogValidationError(f"{label} must be timezone-aware.", field=label)
        if (
            self.starts_at is not None
            and self.ends_at is not None
            and self.ends_at <= self.starts_at
        ):
            raise CatalogValidationError(
                "The window must end after it starts.",
                starts_at=self.starts_at.isoformat(),
                ends_at=self.ends_at.isoformat(),
            )

    @property
    def is_unbounded(self) -> bool:
        """True when the window never closes, so there is nothing to count down."""
        return self.ends_at is None

    def contains(self, moment: datetime) -> bool:
        if self.starts_at is not None and moment < self.starts_at:
            return False
        return not (self.ends_at is not None and moment >= self.ends_at)

    def has_ended(self, moment: datetime) -> bool:
        return self.ends_at is not None and moment >= self.ends_at

    def has_started(self, moment: datetime) -> bool:
        return self.starts_at is None or moment >= self.starts_at

    def seconds_remaining(self, moment: datetime) -> int | None:
        """Drives the countdown timer on flash-sale cards in the Mini App."""
        if self.ends_at is None:
            return None
        return max(0, int((self.ends_at - moment).total_seconds()))
