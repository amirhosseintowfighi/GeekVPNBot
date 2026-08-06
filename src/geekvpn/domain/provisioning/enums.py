"""Order and subscription vocabulary.

These values are duplicated as CHECK constraints in
``infrastructure/persistence/models/provisioning.py``. That duplication is
deliberate: the database must reject a bad state even if it is written by a
migration, a fixture, or a psql session that never loaded this module.
"""

from __future__ import annotations

from enum import StrEnum, unique


@unique
class OrderState(StrEnum):
    """The life of one purchase.

    ``PAID`` and ``ACTIVE`` are separate on purpose. Money arriving and a
    working account are different events, they can be minutes apart when a
    panel is down, and the customer must be told which one has happened.
    """

    PENDING = "pending"
    PAID = "paid"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"

    @property
    def is_open(self) -> bool:
        """Still owed something: either money, or a working account."""
        return self in (
            OrderState.PENDING,
            OrderState.PAID,
            OrderState.PROVISIONING,
        )

    @property
    def is_settled(self) -> bool:
        return self in (
            OrderState.ACTIVE,
            OrderState.CANCELLED,
            OrderState.REFUNDED,
        )


@unique
class SubscriptionState(StrEnum):
    """Why a subscription does or does not carry traffic.

    ``EXPIRED`` and ``EXHAUSTED`` are distinct because the remedy differs: one
    needs a renewal, the other needs more traffic, and telling a customer the
    wrong one is how a renewal turns into a refund request.

    There is no ``EXPIRING`` member. "About to expire" is a function of the
    clock, not a stored fact; storing it would mean a row whose truth depends
    on when a job last ran.
    """

    ACTIVE = "active"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"
    SUSPENDED = "suspended"
    REVOKED = "revoked"

    @property
    def is_usable(self) -> bool:
        return self is SubscriptionState.ACTIVE

    @property
    def is_final(self) -> bool:
        """Nothing short of a new purchase will bring it back."""
        return self is SubscriptionState.REVOKED


@unique
class NodeState(StrEnum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"
    RETIRED = "retired"

    @property
    def accepts_new_accounts(self) -> bool:
        # A degraded node still serves existing customers but must not be
        # handed anyone new: adding load to a struggling node is how a slow
        # node becomes a dead one.
        return self is NodeState.ONLINE


@unique
class OrderSource(StrEnum):
    """Where the purchase came from. Drives attribution, nothing else."""

    BOT = "bot"
    MINIAPP = "miniapp"
    ADMIN = "admin"
    RENEWAL_JOB = "renewal_job"


__all__ = ["NodeState", "OrderSource", "OrderState", "SubscriptionState"]
