"""Operator actions on a live subscription.

The aggregate has had `suspend`, `resume`, `revoke`, `renew` and `add_traffic`
since it was written, and the panel adapters have had `suspend`, `resume`,
`delete_account`, `renew` and `reset_traffic`. Nothing called either set. An
operator could read a subscription and re-read its usage, and that was all -
so a customer sharing their link, or owed a week for an outage, was a database
query and a hand-edited panel.

Every method here does the same two things in the same order: change the panel,
then change our record. That order is deliberate. If the panel call fails we
have not yet promised anything, and the operator sees an error against a
subscription that still says what it said before. The other way round leaves a
row claiming the service is suspended while the account it names keeps working,
which is the failure nobody notices until the customer stops paying.
"""

from __future__ import annotations

from datetime import timedelta

from geekvpn.application.ports.clock import Clock
from geekvpn.application.ports.panel import PanelAdapter
from geekvpn.application.provisioning.ports import (
    NodeRepository,
    PanelProvider,
    SubscriptionRepository,
)
from geekvpn.application.provisioning.provisioning_service import _quota_for
from geekvpn.application.provisioning.usage_sync import _ref_for
from geekvpn.domain.provisioning.errors import SubscriptionNotFound
from geekvpn.domain.provisioning.subscription import Subscription

#: MiB per GiB. Operators think in GiB; the aggregate stores MiB.
MIB_PER_GIB = 1024


class SubscriptionAdminService:
    def __init__(
        self,
        *,
        subscriptions: SubscriptionRepository,
        nodes: NodeRepository,
        panels: PanelProvider,
        clock: Clock,
    ) -> None:
        self._subscriptions = subscriptions
        self._nodes = nodes
        self._panels = panels
        self._clock = clock

    # -- access ------------------------------------------------------------

    async def suspend(self, subscription_id: str, *, reason_fa: str) -> Subscription:
        subscription = await self._load(subscription_id)
        adapter = await self._adapter_for(subscription)
        if adapter is not None:
            await adapter.suspend(_ref_for(subscription), idempotency_key=f"{subscription.id}:sus")
        subscription.suspend(reason_fa=reason_fa)
        return await self._save(subscription)

    async def resume(self, subscription_id: str) -> Subscription:
        subscription = await self._load(subscription_id)
        adapter = await self._adapter_for(subscription)
        if adapter is not None:
            await adapter.resume(_ref_for(subscription), idempotency_key=f"{subscription.id}:res")
        subscription.resume(now=self._clock.now())
        return await self._save(subscription)

    async def revoke(self, subscription_id: str, *, reason_fa: str) -> Subscription:
        """Delete the account on the panel and close the record.

        The row survives on purpose. It is what an order, a payment and a
        refund all point at, and deleting it would leave three other records
        referring to a subscription that never existed.
        """
        subscription = await self._load(subscription_id)
        adapter = await self._adapter_for(subscription)
        if adapter is not None:
            await adapter.delete_account(
                _ref_for(subscription), idempotency_key=f"{subscription.id}:del"
            )
        subscription.revoke(reason_fa=reason_fa, at=self._clock.now())
        return await self._save(subscription)

    # -- what was sold -----------------------------------------------------

    async def extend(self, subscription_id: str, *, days: int) -> Subscription:
        """Add days without charging for them. Goodwill, outages, mistakes."""
        subscription = await self._load(subscription_id)
        adapter = await self._adapter_for(subscription)
        if adapter is not None:
            await adapter.renew(
                _ref_for(subscription),
                extend_by=timedelta(days=days),
                idempotency_key=f"{subscription.id}:ext:{days}",
            )
        subscription.renew(days=days, now=self._clock.now())
        return await self._save(subscription)

    async def add_traffic(self, subscription_id: str, *, gib: int) -> Subscription:
        """Raise the cap on an unlimited plan is meaningless, so it is refused
        by the aggregate rather than silently doing nothing here."""
        subscription = await self._load(subscription_id)
        subscription.add_traffic(extra_mib=gib * MIB_PER_GIB)

        adapter = await self._adapter_for(subscription)
        if adapter is not None and subscription.traffic_limit_mib is not None:
            await adapter.renew(
                _ref_for(subscription),
                new_quota=_quota_for(subscription.traffic_limit_mib),
                idempotency_key=f"{subscription.id}:traffic:{subscription.traffic_limit_mib}",
            )
        return await self._save(subscription)

    async def reset_traffic(self, subscription_id: str) -> Subscription:
        subscription = await self._load(subscription_id)
        adapter = await self._adapter_for(subscription)
        if adapter is not None:
            await adapter.reset_traffic(
                _ref_for(subscription), idempotency_key=f"{subscription.id}:reset"
            )
        subscription.reset_traffic(at=self._clock.now())
        return await self._save(subscription)

    # -- internals ---------------------------------------------------------

    async def _load(self, subscription_id: str) -> Subscription:
        subscription = await self._subscriptions.get(subscription_id)
        if subscription is None:
            raise SubscriptionNotFound(subscription_id=subscription_id)
        return subscription

    async def _adapter_for(self, subscription: Subscription) -> PanelAdapter | None:
        """None when there is nothing on a panel to change.

        A subscription can legitimately have no node - one provisioned before
        its panel was removed, or one that never got that far. Refusing the
        whole action would leave the operator unable to tidy up exactly the
        records that most need tidying.
        """
        if not subscription.node_id or not subscription.remote_username:
            return None
        node = await self._nodes.get(subscription.node_id)
        if node is None:
            return None
        return await self._panels.for_node(node)

    async def _save(self, subscription: Subscription) -> Subscription:
        await self._subscriptions.update(subscription)
        return subscription


__all__ = ["MIB_PER_GIB", "SubscriptionAdminService"]
