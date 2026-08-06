"""Time series and breakdowns -- the two shapes every chart consumes.

These are the wire format for the admin panel's chart components, which is
why each point carries its own Persian label. Sending raw ISO timestamps and
formatting them in TypeScript would put the Jalali calendar in two codebases.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from geekvpn.domain.analytics.calendar import fa_digits
from geekvpn.domain.analytics.enums import Granularity, MetricFormat
from geekvpn.domain.analytics.errors import SeriesMismatch
from geekvpn.domain.analytics.timeframe import DateRange, bucket_label_fa

OTHER_LABEL_FA = "\u0633\u0627\u06cc\u0631"
DEFAULT_TOP_N = 6


@dataclass(frozen=True, slots=True)
class TimePoint:
    """One bucket on a chart."""

    at: datetime
    value: float
    label_fa: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(),
            "value": self.value,
            "labelFa": self.label_fa,
        }


@dataclass(frozen=True, slots=True)
class TimeSeries:
    """An ordered, gap-free run of buckets."""

    key: str
    label_fa: str
    format: MetricFormat
    granularity: Granularity
    points: tuple[TimePoint, ...] = ()

    # ---- Construction ---------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        key: str,
        label_fa: str,
        format: MetricFormat,
        range: DateRange,
        values: dict[datetime, float],
        granularity: Granularity | None = None,
    ) -> TimeSeries:
        """Fill every bucket in the range, defaulting to zero.

        Callers pass a sparse map keyed by bucket start. Missing buckets
        become explicit zeros: a chart that silently skips an empty Friday
        misreports the weekend.
        """
        step = granularity or range.suggested_granularity()
        points = tuple(
            TimePoint(
                at=bucket,
                value=float(values.get(bucket, 0.0)),
                label_fa=bucket_label_fa(bucket, step),
            )
            for bucket in range.buckets(step)
        )
        return cls(
            key=key,
            label_fa=label_fa,
            format=format,
            granularity=step,
            points=points,
        )

    # ---- Aggregates -----------------------------------------------------

    @property
    def values(self) -> tuple[float, ...]:
        return tuple(point.value for point in self.points)

    def total(self) -> float:
        return sum(self.values)

    def average(self) -> float:
        return self.total() / len(self.points) if self.points else 0.0

    def peak(self) -> TimePoint | None:
        return max(self.points, key=lambda p: p.value) if self.points else None

    def trough(self) -> TimePoint | None:
        return min(self.points, key=lambda p: p.value) if self.points else None

    def is_empty(self) -> bool:
        return not any(self.values)

    def moving_average(self, window: int = 7) -> TimeSeries:
        """Smooth a spiky daily series.

        Leading buckets average over however many points exist rather than
        being dropped, so the smoothed line starts where the raw one does.
        """
        if window < 2 or not self.points:
            return self
        smoothed: list[TimePoint] = []
        for index, point in enumerate(self.points):
            start = max(0, index - window + 1)
            chunk = self.values[start : index + 1]
            smoothed.append(
                TimePoint(
                    at=point.at,
                    value=sum(chunk) / len(chunk),
                    label_fa=point.label_fa,
                )
            )
        return TimeSeries(
            key=f"{self.key}_ma{window}",
            label_fa=self.label_fa,
            format=self.format,
            granularity=self.granularity,
            points=tuple(smoothed),
        )

    def cumulative(self) -> TimeSeries:
        running = 0.0
        points: list[TimePoint] = []
        for point in self.points:
            running += point.value
            points.append(TimePoint(at=point.at, value=running, label_fa=point.label_fa))
        return TimeSeries(
            key=f"{self.key}_cumulative",
            label_fa=self.label_fa,
            format=self.format,
            granularity=self.granularity,
            points=tuple(points),
        )

    def ratio_to(self, other: TimeSeries, *, key: str, label_fa: str) -> TimeSeries:
        """Divide bucket by bucket, e.g. orders over visitors.

        Division by zero yields zero rather than an exception: a day with no
        visitors has no conversion rate, and a chart is not the place to argue
        about that.
        """
        if len(self.points) != len(other.points):
            raise SeriesMismatch(
                "Series cover different buckets.",
                left=len(self.points),
                right=len(other.points),
            )
        points = tuple(
            TimePoint(
                at=mine.at,
                value=(mine.value / theirs.value * 100.0) if theirs.value else 0.0,
                label_fa=mine.label_fa,
            )
            for mine, theirs in zip(self.points, other.points, strict=True)
        )
        return TimeSeries(
            key=key,
            label_fa=label_fa,
            format=MetricFormat.PERCENT,
            granularity=self.granularity,
            points=points,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "labelFa": self.label_fa,
            "format": str(self.format),
            "granularity": str(self.granularity),
            "total": self.total(),
            "points": [point.as_dict() for point in self.points],
        }


@dataclass(frozen=True, slots=True)
class BreakdownSlice:
    """One row of a composition chart."""

    key: str
    label_fa: str
    value: float
    share: float = 0.0

    def share_fa(self) -> str:
        return f"{fa_digits(round(self.share))}\u066a"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "labelFa": self.label_fa,
            "value": self.value,
            "share": self.share,
        }


@dataclass(frozen=True, slots=True)
class Breakdown:
    """A composition: revenue by plan, orders by payment method, and so on."""

    key: str
    label_fa: str
    format: MetricFormat
    slices: tuple[BreakdownSlice, ...] = ()

    @classmethod
    def build(
        cls,
        *,
        key: str,
        label_fa: str,
        format: MetricFormat,
        rows: dict[str, float],
        labels: dict[str, str] | None = None,
        top_n: int = DEFAULT_TOP_N,
    ) -> Breakdown:
        """Rank, compute shares and fold the tail into \u0633\u0627\u06cc\u0631.

        A donut with thirty slices communicates nothing, so everything past
        ``top_n`` is summed into one honest "other" slice rather than dropped.
        """
        names = labels or {}
        total = sum(rows.values())
        ranked = sorted(rows.items(), key=lambda item: item[1], reverse=True)
        head, tail = ranked[:top_n], ranked[top_n:]

        def share(value: float) -> float:
            return (value / total * 100.0) if total else 0.0

        slices = [
            BreakdownSlice(
                key=name,
                label_fa=names.get(name, name),
                value=value,
                share=share(value),
            )
            for name, value in head
        ]
        if tail:
            other = sum(value for _, value in tail)
            slices.append(
                BreakdownSlice(
                    key="other",
                    label_fa=OTHER_LABEL_FA,
                    value=other,
                    share=share(other),
                )
            )
        return cls(key=key, label_fa=label_fa, format=format, slices=tuple(slices))

    def total(self) -> float:
        return sum(item.value for item in self.slices)

    def top(self) -> BreakdownSlice | None:
        return self.slices[0] if self.slices else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "labelFa": self.label_fa,
            "format": str(self.format),
            "total": self.total(),
            "slices": [item.as_dict() for item in self.slices],
        }


__all__ = [
    "DEFAULT_TOP_N",
    "OTHER_LABEL_FA",
    "Breakdown",
    "BreakdownSlice",
    "TimePoint",
    "TimeSeries",
]
