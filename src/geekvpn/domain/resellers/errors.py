"""What can go wrong, as types the API layer can map to status codes."""

from __future__ import annotations


class ResellerError(Exception):
    """Base for everything in this package."""


class ResellerNotFound(ResellerError):
    pass


class ResellerSuspended(ResellerError):
    """Provisioning attempted by an account that is not active."""


class InsufficientCredit(ResellerError):
    """The balance will not cover this sale.

    Carries both numbers because the message a reseller sees has to say how
    much to top up by, and computing that twice is how the two drift.
    """

    def __init__(self, *, needed: int, available: int) -> None:
        super().__init__("Reseller credit will not cover this purchase.")
        self.needed = needed
        self.available = available

    @property
    def shortfall(self) -> int:
        return max(0, self.needed - self.available)


class NodeNotAllowed(ResellerError):
    """A reseller tried to provision on a panel they were not given."""

    def __init__(self, node_id: str) -> None:
        super().__init__("That panel is not available to this reseller.")
        self.node_id = node_id


__all__ = [
    "InsufficientCredit",
    "NodeNotAllowed",
    "ResellerError",
    "ResellerNotFound",
    "ResellerSuspended",
]
