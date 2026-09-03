"""Immutable value objects exchanged with adapters.

All of these are frozen. An adapter must never be able to mutate the spec it
was handed, and a caller must never be able to mutate a usage reading it was
given - both have caused real billing incidents in systems like this.

Units are stated once, here, and never re-litigated: **traffic is bytes**,
**time is timezone-aware UTC**. Panels variously use GB, MB, and naive local
timestamps; converting at the adapter boundary is mandatory.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from geekvpn.domain.panels.enums import AccountState, Protocol, SubscriptionFormat

BYTES_PER_GIB = 1024**3


@dataclass(frozen=True, slots=True)
class TrafficQuota:
    """A data cap. `None` or 0 total means unlimited."""

    total_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.total_bytes is not None and self.total_bytes < 0:
            raise ValueError("total_bytes cannot be negative")

    @property
    def is_unlimited(self) -> bool:
        return self.total_bytes is None or self.total_bytes == 0

    @classmethod
    def from_gib(cls, gib: float | None) -> TrafficQuota:
        if gib is None:
            return cls(None)
        return cls(round(gib * BYTES_PER_GIB))

    @property
    def total_gib(self) -> float | None:
        if self.total_bytes is None:
            return None
        return self.total_bytes / BYTES_PER_GIB


@dataclass(frozen=True, slots=True)
class PanelGroup:
    """One access group on a panel that has the concept.

    PasarGuard grants access through groups, and which group an account joins
    decides which configs it gets - so two customers on the same node can hold
    entirely different inbounds. That makes the group a selling decision, not a
    connection detail, which is why it is a first-class value rather than a
    string in a config blob.

    `id` is what the panel wants back; `name` is what an operator recognises.
    Sending the name would work on some panels and silently grant nothing on
    others.
    """

    id: str
    name: str
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class PanelAccountRef:
    """Stable pointer to an account on one specific panel.

    `username` is what most panels key on, but 3x-ui-family panels also need
    the owning inbound and the client UUID, so `external_id` and `container_id`
    carry that without leaking the concept into the core model.
    """

    panel_id: uuid.UUID
    username: str
    external_id: str | None = None
    container_id: str | None = None

    def __post_init__(self) -> None:
        if not self.username:
            raise ValueError("username is required")


@dataclass(frozen=True, slots=True)
class AccountSpec:
    """What we want to exist on the panel.

    Declarative on purpose: an adapter is free to reach this state by whatever
    sequence of calls its panel requires.
    """

    username: str
    quota: TrafficQuota
    expires_at: datetime | None
    protocols: tuple[Protocol, ...] = ()
    #: Panel-side grouping: Marzban inbounds, Marzneshin services, 3x-ui
    #: inbound ids, PasarGuard groups. Opaque to the core.
    group_tags: tuple[str, ...] = ()
    device_limit: int | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.username:
            raise ValueError("username is required")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        if self.device_limit is not None and self.device_limit < 0:
            raise ValueError("device_limit cannot be negative")


@dataclass(frozen=True, slots=True)
class AccountUsage:
    """A traffic reading.

    `measured_at` is not decoration. Panels cache and nodes report late, so a
    reading without a timestamp cannot be safely compared with the previous one
    to compute a delta.
    """

    used_bytes: int
    measured_at: datetime
    quota: TrafficQuota = field(default_factory=TrafficQuota)
    #: When the panel last saw this account connected, if it says.
    #:
    #: The real answer to "when did they last use it". Traffic counters only
    #: move when bytes flow, so deriving it from them says nothing about a
    #: customer who connected and could not reach anything - which is exactly
    #: the customer worth asking about.
    online_at: datetime | None = None

    @property
    def remaining_bytes(self) -> int | None:
        if self.quota.is_unlimited or self.quota.total_bytes is None:
            return None
        return max(0, self.quota.total_bytes - self.used_bytes)

    @property
    def fraction_used(self) -> float | None:
        if self.quota.is_unlimited or not self.quota.total_bytes:
            return None
        return min(1.0, self.used_bytes / self.quota.total_bytes)


@dataclass(frozen=True, slots=True)
class PanelAccount:
    """The full remote view of an account."""

    ref: PanelAccountRef
    state: AccountState
    usage: AccountUsage
    expires_at: datetime | None = None
    subscription_url: str | None = None
    links: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NodeInfo:
    name: str
    address: str
    is_healthy: bool
    external_id: str | None = None
    xray_version: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class PanelHealth:
    is_healthy: bool
    latency_ms: float | None = None
    version: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class SubscriptionPayload:
    content: str
    content_type: str
    fmt: SubscriptionFormat = SubscriptionFormat.AUTO
