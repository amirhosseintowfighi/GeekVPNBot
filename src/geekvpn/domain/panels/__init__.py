"""Panel domain: the vendor-neutral vocabulary for remote VPN panels.

Nothing in this package imports httpx, a panel SDK, or any adapter. That is
the whole point: the business layer talks about "an account with a quota that
expires", never about Marzban's `/api/user` or 3x-ui's nested clients.
"""

from geekvpn.domain.panels.enums import (
    AccountState,
    Capability,
    PanelKind,
    Protocol,
    SubscriptionFormat,
)
from geekvpn.domain.panels.errors import (
    AccountAlreadyExists,
    AccountNotFound,
    CapabilityNotSupported,
    PanelAuthFailed,
    PanelContractViolation,
    PanelError,
    PanelRateLimited,
    PanelUnreachable,
    QuotaExceeded,
)
from geekvpn.domain.panels.values import (
    AccountSpec,
    AccountUsage,
    NodeInfo,
    PanelAccount,
    PanelAccountRef,
    PanelHealth,
    SubscriptionPayload,
    TrafficQuota,
)

__all__ = [
    "AccountAlreadyExists",
    "AccountNotFound",
    "AccountSpec",
    "AccountState",
    "AccountUsage",
    "Capability",
    "CapabilityNotSupported",
    "NodeInfo",
    "PanelAccount",
    "PanelAccountRef",
    "PanelAuthFailed",
    "PanelContractViolation",
    "PanelError",
    "PanelHealth",
    "PanelKind",
    "PanelRateLimited",
    "PanelUnreachable",
    "Protocol",
    "QuotaExceeded",
    "SubscriptionFormat",
    "SubscriptionPayload",
    "TrafficQuota",
]
