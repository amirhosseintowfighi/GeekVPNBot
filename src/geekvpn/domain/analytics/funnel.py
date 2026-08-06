"""The purchase funnel and its conversion rates.

Two rates matter and they answer different questions. Step conversion asks
"of the people who got here, how many moved on" -- that is where a broken
screen shows up. Overall conversion asks "of everyone who started, how many
ended up with a working VPN" -- that is the number the business lives on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from geekvpn.domain.analytics.enums import FunnelStage, MetricFormat
from geekvpn.domain.analytics.metrics import ratio_percent
from geekvpn.domain.analytics.series import Breakdown

LEAK_THRESHOLD_PERCENT = 40.0
"""A step that loses more than this share is flagged as the worst leak."""


@dataclass(frozen=True, slots=True)
class FunnelStep:
    """One stage with its counts already worked out."""

    stage: FunnelStage
    count: int
    previous_count: int
    first_count: int

    @property
    def label_fa(self) -> str:
        return self.stage.label_fa()

    @property
    def step_rate(self) -> float:
        """Share of the previous stage that reached this one."""
        if self.stage.position() == 0:
            return 100.0
        return ratio_percent(self.count, self.previous_count)

    @property
    def overall_rate(self) -> float:
        return ratio_percent(self.count, self.first_count)

    @property
    def dropped(self) -> int:
        if self.stage.position() == 0:
            return 0
        return max(0, self.previous_count - self.count)

    @property
    def drop_rate(self) -> float:
        return 100.0 - self.step_rate if self.stage.position() else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": str(self.stage),
            "labelFa": self.label_fa,
            "count": self.count,
            "stepRate": self.step_rate,
            "overallRate": self.overall_rate,
            "dropped": self.dropped,
            "dropRate": self.drop_rate,
        }


@dataclass(frozen=True, slots=True)
class Funnel:
    """The whole funnel for one period."""

    steps: tuple[FunnelStep, ...] = ()

    @classmethod
    def build(cls, counts: dict[FunnelStage, int]) -> Funnel:
        """Assemble from raw stage counts.

        Counts are forced to be monotonically non-increasing. Event data is
        messy -- a retried payment can produce more approvals than invoices --
        and a funnel that widens halfway down is nonsense on a chart.
        """
        ordered = FunnelStage.ordered()
        cleaned: list[int] = []
        ceiling: int | None = None
        for stage in ordered:
            value = max(0, int(counts.get(stage, 0)))
            if ceiling is not None:
                value = min(value, ceiling)
            cleaned.append(value)
            ceiling = value

        first = cleaned[0] if cleaned else 0
        steps = tuple(
            FunnelStep(
                stage=stage,
                count=value,
                previous_count=cleaned[index - 1] if index else value,
                first_count=first,
            )
            for index, (stage, value) in enumerate(zip(ordered, cleaned, strict=True))
        )
        return cls(steps=steps)

    def step(self, stage: FunnelStage) -> FunnelStep | None:
        for item in self.steps:
            if item.stage is stage:
                return item
        return None

    @property
    def entered(self) -> int:
        return self.steps[0].count if self.steps else 0

    @property
    def completed(self) -> int:
        return self.steps[-1].count if self.steps else 0

    def conversion_rate(self) -> float:
        return ratio_percent(self.completed, self.entered)

    def worst_leak(self) -> FunnelStep | None:
        """The step that loses the most people, ignoring the entry stage."""
        candidates = [item for item in self.steps if item.stage.position() > 0]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.dropped)

    def needs_attention(self) -> bool:
        leak = self.worst_leak()
        return bool(leak and leak.drop_rate >= LEAK_THRESHOLD_PERCENT)

    def payment_completion_rate(self) -> float:
        """Approved payments that actually became a working service."""
        approved = self.step(FunnelStage.PAYMENT_APPROVED)
        provisioned = self.step(FunnelStage.PROVISIONED)
        if not approved or not provisioned:
            return 0.0
        return ratio_percent(provisioned.count, approved.count)

    def to_breakdown(self) -> Breakdown:
        return Breakdown.build(
            key="funnel",
            label_fa="\u0642\u06cc\u0641 \u062e\u0631\u06cc\u062f",
            format=MetricFormat.COUNT,
            rows={str(item.stage): float(item.count) for item in self.steps},
            labels={str(item.stage): item.label_fa for item in self.steps},
            top_n=len(self.steps),
        )

    def as_dict(self) -> dict[str, Any]:
        leak = self.worst_leak()
        return {
            "entered": self.entered,
            "completed": self.completed,
            "conversionRate": self.conversion_rate(),
            "paymentCompletionRate": self.payment_completion_rate(),
            "worstLeak": leak.as_dict() if leak else None,
            "steps": [item.as_dict() for item in self.steps],
        }


__all__ = ["LEAK_THRESHOLD_PERCENT", "Funnel", "FunnelStep"]
