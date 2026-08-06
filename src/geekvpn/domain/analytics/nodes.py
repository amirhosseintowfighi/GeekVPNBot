"""Node and server usage.

This is capacity planning, not billing. The question is which node is about
to fall over and whether the traffic customers paid for is actually being
delivered somewhere with room to spare.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from geekvpn.domain.analytics.enums import MetricFormat
from geekvpn.domain.analytics.metrics import ratio_percent
from geekvpn.domain.analytics.series import Breakdown

WARN_LOAD_PERCENT = 75.0
CRITICAL_LOAD_PERCENT = 90.0


@dataclass(frozen=True, slots=True)
class NodeUsage:
    """One panel node over the reporting period."""

    node_id: str
    name: str
    country_fa: str = ""
    online: bool = True
    accounts: int = 0
    capacity: int = 0
    traffic_gib: float = 0.0
    uptime_percent: float = 100.0

    @property
    def load_percent(self) -> float:
        return ratio_percent(self.accounts, self.capacity)

    @property
    def free_slots(self) -> int:
        return max(0, self.capacity - self.accounts)

    def is_critical(self) -> bool:
        return not self.online or self.load_percent >= CRITICAL_LOAD_PERCENT

    def needs_attention(self) -> bool:
        return self.is_critical() or self.load_percent >= WARN_LOAD_PERCENT

    def health_fa(self) -> str:
        if not self.online:
            return "\u0622\u0641\u0644\u0627\u06cc\u0646"
        if self.load_percent >= CRITICAL_LOAD_PERCENT:
            return "\u0627\u0634\u0628\u0627\u0639"
        if self.load_percent >= WARN_LOAD_PERCENT:
            return "\u067e\u0631\u0628\u0627\u0631"
        return "\u0633\u0627\u0644\u0645"

    def as_dict(self) -> dict[str, Any]:
        return {
            "nodeId": self.node_id,
            "name": self.name,
            "countryFa": self.country_fa,
            "online": self.online,
            "accounts": self.accounts,
            "capacity": self.capacity,
            "loadPercent": self.load_percent,
            "freeSlots": self.free_slots,
            "trafficGib": self.traffic_gib,
            "uptimePercent": self.uptime_percent,
            "healthFa": self.health_fa(),
        }


@dataclass(frozen=True, slots=True)
class FleetUsage:
    """Every node together."""

    nodes: tuple[NodeUsage, ...] = ()

    @property
    def online_nodes(self) -> int:
        return sum(1 for node in self.nodes if node.online)

    @property
    def total_accounts(self) -> int:
        return sum(node.accounts for node in self.nodes)

    @property
    def total_capacity(self) -> int:
        """Offline nodes contribute no capacity -- that is the point."""
        return sum(node.capacity for node in self.nodes if node.online)

    @property
    def total_traffic_gib(self) -> float:
        return sum(node.traffic_gib for node in self.nodes)

    @property
    def load_percent(self) -> float:
        return ratio_percent(self.total_accounts, self.total_capacity)

    def hottest(self) -> NodeUsage | None:
        return max(self.nodes, key=lambda n: n.load_percent, default=None)

    def attention_list(self) -> tuple[NodeUsage, ...]:
        return tuple(
            sorted(
                (node for node in self.nodes if node.needs_attention()),
                key=lambda n: (not n.online, -n.load_percent),
            )
        )

    def traffic_breakdown(self) -> Breakdown:
        return Breakdown.build(
            key="traffic_by_node",
            label_fa="\u0645\u0635\u0631\u0641 \u0628\u0647 \u062a\u0641\u06a9\u06cc\u06a9 \u0633\u0631\u0648\u0631",
            format=MetricFormat.GIB,
            rows={node.node_id: node.traffic_gib for node in self.nodes},
            labels={node.node_id: node.name for node in self.nodes},
        )

    def as_dict(self) -> dict[str, Any]:
        hottest = self.hottest()
        return {
            "nodes": [node.as_dict() for node in self.nodes],
            "onlineNodes": self.online_nodes,
            "totalNodes": len(self.nodes),
            "totalAccounts": self.total_accounts,
            "totalCapacity": self.total_capacity,
            "loadPercent": self.load_percent,
            "totalTrafficGib": self.total_traffic_gib,
            "hottest": hottest.as_dict() if hottest else None,
            "attention": [node.as_dict() for node in self.attention_list()],
        }


__all__ = [
    "CRITICAL_LOAD_PERCENT",
    "WARN_LOAD_PERCENT",
    "FleetUsage",
    "NodeUsage",
]
