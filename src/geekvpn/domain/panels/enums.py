"""Panel vocabulary.

`Capability` is the load-bearing type here. Panels are NOT feature-equivalent:
3x-ui cannot extend an expiry without rewriting the client object, Marzneshin
models access through "services" rather than inbounds, and only some panels
expose per-node statistics. Rather than pretend otherwise and fail at runtime
in front of a paying customer, every adapter declares what it can do and the
orchestration layer plans around it.
"""

from __future__ import annotations

from enum import StrEnum, unique


@unique
class PanelKind(StrEnum):
    """Registry keys. Adding a panel adds a member here and nothing else."""

    PASARGUARD = "pasarguard"
    MARZBAN = "marzban"
    MARZNESHIN = "marzneshin"
    SANAEI = "sanaei"
    ALIREZA = "alireza"


@unique
class Capability(StrEnum):
    """Optional behaviours an adapter may advertise.

    Anything NOT listed here is mandatory and every adapter must implement it:
    create, get, delete, suspend, resume, usage, renew, health. Those are the
    irreducible core of selling a subscription.
    """

    #: Can zero a user's consumed traffic without recreating the account.
    RESET_TRAFFIC = "reset_traffic"
    #: Can extend an expiry in place (rather than delete-and-recreate).
    NATIVE_EXPIRY_EXTEND = "native_expiry_extend"
    #: Can raise the data cap in place.
    NATIVE_QUOTA_EXTEND = "native_quota_extend"
    #: Can return usage for many accounts in one round trip.
    BULK_USAGE = "bulk_usage"
    #: Exposes individual nodes/servers and their health.
    NODE_INVENTORY = "node_inventory"
    #: Can pin an account to a subset of nodes.
    PER_NODE_ASSIGNMENT = "per_node_assignment"
    #: Serves a ready-made subscription document (Clash, sing-box, v2ray...).
    SUBSCRIPTION_URL = "subscription_url"
    #: Enforces a concurrent-device / IP limit.
    DEVICE_LIMIT = "device_limit"


@unique
class AccountState(StrEnum):
    """Normalised remote account state.

    Every panel spells these differently ('active'/'disabled'/'limited'/
    'expired'/'on_hold'). The mapping happens once, inside each adapter, so the
    rest of the platform sees exactly five values.
    """

    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    QUOTA_EXHAUSTED = "quota_exhausted"
    UNKNOWN = "unknown"

    @property
    def is_usable(self) -> bool:
        """Whether traffic will actually flow for an account in this state."""
        return self is AccountState.ACTIVE


@unique
class Protocol(StrEnum):
    VLESS = "vless"
    VMESS = "vmess"
    TROJAN = "trojan"
    SHADOWSOCKS = "shadowsocks"
    WIREGUARD = "wireguard"
    HYSTERIA2 = "hysteria2"
    TUIC = "tuic"


@unique
class SubscriptionFormat(StrEnum):
    """Wire formats a client app might ask for."""

    AUTO = "auto"
    V2RAY = "v2ray"
    CLASH = "clash"
    CLASH_META = "clash-meta"
    SING_BOX = "sing-box"
    OUTLINE = "outline"
