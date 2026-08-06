"""Single-number metrics and their period-over-period deltas.

A number without a comparison is decoration. Every card here carries the
previous period's value and works out the arrow itself, so the panel never
has to decide whether a rising churn rate should be painted green.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from geekvpn.domain.analytics.calendar import fa_digits
from geekvpn.domain.analytics.enums import MetricFormat, MetricKey, TrendDirection

FLAT_THRESHOLD_PERCENT = 1.0
"""Below this, movement is noise and the card reads \u0628\u062f\u0648\u0646 \u062a\u063a\u06cc\u06cc\u0631."""

THOUSANDS_SEP = "\u066c"
DECIMAL_SEP = "\u066b"
TOMAN = "\u062a\u0648\u0645\u0627\u0646"
GIB = "\u06af\u06cc\u06af\u0627\u0628\u0627\u06cc\u062a"
DAY = "\u0631\u0648\u0632"


def fa_number(value: float, *, decimals: int = 0) -> str:
    """Group with the Persian thousands separator, not a comma."""
    rounded = round(value, decimals)
    whole = int(abs(rounded))
    grouped = f"{whole:,}".replace(",", THOUSANDS_SEP)
    out = fa_digits(grouped)
    if decimals:
        fraction = abs(rounded) - whole
        digits = str(round(fraction * (10**decimals))).rjust(decimals, "0")
        if int(digits):
            out = f"{out}{DECIMAL_SEP}{fa_digits(digits)}"
    return f"-{out}" if rounded < 0 else out


def format_value(value: float, format: MetricFormat) -> str:
    """Render one number the way its unit demands."""
    if format is MetricFormat.TOMAN:
        return f"{fa_number(value)} {TOMAN}"
    if format is MetricFormat.PERCENT:
        return f"{fa_number(value, decimals=1)}\u066a"
    if format is MetricFormat.GIB:
        return f"{fa_number(value, decimals=1)} {GIB}"
    if format is MetricFormat.DAYS:
        return f"{fa_number(value)} {DAY}"
    return fa_number(value)


def percent_change(current: float, previous: float) -> float | None:
    """Growth in percent, or None when there is no baseline.

    Going from zero to anything is not "infinite growth"; it is a first data
    point, and the card shows a dash.
    """
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100.0


def ratio_percent(numerator: float, denominator: float) -> float:
    return (numerator / denominator * 100.0) if denominator else 0.0


def safe_divide(numerator: float, denominator: float) -> float:
    return (numerator / denominator) if denominator else 0.0


@dataclass(frozen=True, slots=True)
class MetricCard:
    """One headline number with its comparison."""

    key: MetricKey
    value: float
    previous: float = 0.0
    label_fa: str = ""
    hint_fa: str = ""

    @classmethod
    def of(
        cls,
        key: MetricKey,
        value: float,
        *,
        previous: float = 0.0,
        hint_fa: str = "",
    ) -> MetricCard:
        return cls(
            key=key,
            value=value,
            previous=previous,
            label_fa=key.label_fa(),
            hint_fa=hint_fa,
        )

    @property
    def format(self) -> MetricFormat:
        return self.key.format()

    def change_percent(self) -> float | None:
        return percent_change(self.value, self.previous)

    def direction(self) -> TrendDirection:
        change = self.change_percent()
        if change is None or abs(change) < FLAT_THRESHOLD_PERCENT:
            return TrendDirection.FLAT
        return TrendDirection.UP if change > 0 else TrendDirection.DOWN

    def is_improvement(self) -> bool | None:
        """Whether the movement is good news for this particular metric."""
        direction = self.direction()
        if direction is TrendDirection.FLAT:
            return None
        rising = direction is TrendDirection.UP
        return not rising if self.key.lower_is_better() else rising

    def value_fa(self) -> str:
        return format_value(self.value, self.format)

    def change_fa(self) -> str:
        change = self.change_percent()
        if change is None:
            return "\u2014"
        sign = "+" if change > 0 else "\u2212" if change < 0 else ""
        return f"{sign}{fa_number(abs(change), decimals=1)}\u066a"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": str(self.key),
            "labelFa": self.label_fa or self.key.label_fa(),
            "format": str(self.format),
            "value": self.value,
            "previous": self.previous,
            "valueFa": self.value_fa(),
            "changePercent": self.change_percent(),
            "changeFa": self.change_fa(),
            "direction": str(self.direction()),
            "isImprovement": self.is_improvement(),
            "hintFa": self.hint_fa,
        }


__all__ = [
    "FLAT_THRESHOLD_PERCENT",
    "MetricCard",
    "fa_number",
    "format_value",
    "percent_change",
    "ratio_percent",
    "safe_divide",
]
