"""The Base Panel Interface.

This is the contract the entire platform is written against. There is exactly
one rule for changing it: **adding a panel must never require editing this
file.** If a new panel tempts you to add a method, the right move is almost
always a new `Capability` instead.

Why a `Protocol` rather than an ABC:

- Adapters do not inherit from anything they must import, so a third-party
  adapter package never takes a hard dependency on our class hierarchy.
- Test doubles satisfy it structurally, with no registration ceremony.
- `mypy` still enforces the full signature at every call site.

The shared HTTP plumbing lives in `infrastructure.panels.base` as a *helper you
may compose*, deliberately not as a base class you must extend. Composition
over inheritance: an adapter for a panel that speaks gRPC or SSH should not be
forced through an HTTP-shaped hierarchy.

Idempotency: every mutating method takes `idempotency_key`. Provisioning is a
distributed transaction across our database and someone else's panel, over a
network that drops responses. Retries are guaranteed, so exactly-once must be
engineered rather than hoped for.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import ClassVar, Protocol, runtime_checkable

from geekvpn.domain.panels.enums import Capability, PanelKind, SubscriptionFormat
from geekvpn.domain.panels.values import (
    AccountSpec,
    AccountUsage,
    NodeInfo,
    PanelAccount,
    PanelAccountRef,
    PanelGroup,
    PanelHealth,
    SubscriptionPayload,
    TrafficQuota,
)


@runtime_checkable
class PanelAdapter(Protocol):
    """Everything the platform is allowed to ask of a VPN panel."""

    #: Registry key. Must match the `@register_panel` decorator.
    kind: ClassVar[PanelKind]

    #: Optional behaviours this adapter supports. Callers MUST consult this
    #: before invoking a capability-gated method.
    capabilities: ClassVar[frozenset[Capability]]

    # -- lifecycle ---------------------------------------------------------

    async def health(self) -> PanelHealth:
        """Cheap liveness probe. Must never raise; report failure in the result."""
        ...

    async def close(self) -> None:
        """Release sockets. Safe to call twice."""
        ...

    # -- account lifecycle (mandatory) -------------------------------------

    async def create_account(self, spec: AccountSpec, *, idempotency_key: str) -> PanelAccount:
        """Create the account, or return the existing one if it already matches.

        Raises `AccountAlreadyExists` only when a *different* account holds the
        username.
        """
        ...

    async def get_account(self, ref: PanelAccountRef) -> PanelAccount: ...

    async def find_by_subscription(self, url: str) -> PanelAccount | None:
        """Locate an account from its subscription link.

        For a customer who bought through support and now wants the bot to
        manage it: the link is the only thing they have, and on most panels it
        carries an opaque token rather than the username.

        Returns `None` when nothing matches, including on a panel that cannot
        search at all. Not an exception - "not here" is the ordinary answer
        while asking each node in turn, and only the last silence means
        anything.
        """
        ...

    async def delete_account(self, ref: PanelAccountRef, *, idempotency_key: str) -> None:
        """Delete. Deleting an already-absent account MUST succeed silently,
        because a retried delete is indistinguishable from a first one."""
        ...

    async def suspend(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount: ...

    async def resume(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount: ...

    async def usage(self, ref: PanelAccountRef) -> AccountUsage: ...

    # -- renewal -----------------------------------------------------------

    async def renew(
        self,
        ref: PanelAccountRef,
        *,
        extend_by: timedelta | None = None,
        new_expires_at: datetime | None = None,
        new_quota: TrafficQuota | None = None,
        idempotency_key: str,
    ) -> PanelAccount:
        """Move the expiry and/or the cap.

        Adapters without `NATIVE_EXPIRY_EXTEND` emulate this by reading the
        current values and writing absolute replacements, which is why the
        method accepts both a relative and an absolute form.
        """
        ...

    # -- capability-gated --------------------------------------------------

    async def reset_traffic(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        """Requires `Capability.RESET_TRAFFIC`."""
        ...

    async def bulk_usage(self, refs: Sequence[PanelAccountRef]) -> Mapping[str, AccountUsage]:
        """Requires `Capability.BULK_USAGE`. Keyed by username."""
        ...

    async def groups(self) -> Sequence[PanelGroup]:
        """Access groups this panel offers, for an operator to choose from.

        Requires `Capability.ACCESS_GROUPS`. Panels without the concept raise
        rather than returning an empty list: "this panel has no groups" and
        "this panel has none configured" need different answers on screen.
        """
        ...

    async def nodes(self) -> Sequence[NodeInfo]:
        """Requires `Capability.NODE_INVENTORY`."""
        ...

    async def subscription(
        self, ref: PanelAccountRef, *, fmt: SubscriptionFormat = SubscriptionFormat.AUTO
    ) -> SubscriptionPayload:
        """Requires `Capability.SUBSCRIPTION_URL`."""
        ...
