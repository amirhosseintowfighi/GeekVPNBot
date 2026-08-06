"""Analytics failures.

Analytics is a read model: it must degrade rather than explode. These errors
are for genuinely impossible inputs -- a range that ends before it starts, a
metric that does not exist -- not for thin data. An empty week is a valid
answer and returns zeros.
"""

from __future__ import annotations

from geekvpn.domain.base import ValidationError


class AnalyticsError(ValidationError):
    """Base class for analytics validation failures."""


class InvalidDateRange(AnalyticsError):
    def __init__(self, message: str = "", **details: object) -> None:
        super().__init__(
            message
            or "\u0628\u0627\u0632\u0647\u0654 \u0632\u0645\u0627\u0646\u06cc \u0646\u0627\u0645\u0639\u062a\u0628\u0631 \u0627\u0633\u062a.",
            **details,
        )


class UnknownMetric(AnalyticsError):
    def __init__(self, key: str) -> None:
        super().__init__(
            "\u0634\u0627\u062e\u0635 \u0645\u0648\u0631\u062f \u0646\u0638\u0631 \u0648\u062c\u0648\u062f \u0646\u062f\u0627\u0631\u062f.",
            key=key,
        )


class SeriesMismatch(AnalyticsError):
    """Two series were combined but do not cover the same buckets."""


__all__ = [
    "AnalyticsError",
    "InvalidDateRange",
    "SeriesMismatch",
    "UnknownMetric",
]
