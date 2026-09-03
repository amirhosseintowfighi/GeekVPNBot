"""Reading traffic usage back from the panels.

Nothing else in the platform writes ``traffic_used_mib``, so without this the
figure stays at zero forever: the quota reminder never fires, the exhausted
state is never reached, and an unlimited-in-practice account looks metered in
the UI.

Two shapes, one implementation:

* :meth:`UsageSyncService.sync_subscription` - one account, for the operator's
  "sync now" button.
* :meth:`UsageSyncService.sync_node` - **one batched call per node**, for the
  scheduled job. Per-customer requests would mean thousands of round trips to
  somebody else's Marzban on every tick.

A node that is unreachable is recorded and skipped. One dead panel must not stop
the others from syncing, which is why the per-node loop swallows `PanelError`
and reports it rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from geekvpn.application.ports.clock import Clock
from geekvpn.application.provisioning.ports import (
    NodeRepository,
    PanelProvider,
    SubscriptionRepository,
)
from geekvpn.domain.panels.values import PanelAccountRef
from geekvpn.domain.provisioning.subscription import Subscription

#: Panels report bytes; the subscription stores MiB.
BYTES_PER_MIB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class NodeSyncReport:
    node_id: str
    updated: int = 0
    skipped: int = 0
    error: str | None = None


@dataclass(slots=True)
class SyncReport:
    """What one full pass did, for the worker log."""

    nodes: list[NodeSyncReport] = field(default_factory=list)

    @property
    def updated(self) -> int:
        return sum(n.updated for n in self.nodes)

    @property
    def failed_nodes(self) -> list[str]:
        return [n.node_id for n in self.nodes if n.error is not None]


class UsageSyncService:
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

    async def sync_subscription(self, subscription_id: str) -> Subscription | None:
        """Refresh one account. Returns ``None`` when there is nothing to ask.

        A subscription with no node or no remote username was never actually
        created on a panel, so there is no reading to fetch - that is a
        provisioning problem, not a sync problem.
        """
        subscription = await self._subscriptions.get(subscription_id)
        if subscription is None:
            return None
        if not subscription.node_id or not subscription.remote_username:
            return None

        node = await self._nodes.get(subscription.node_id)
        if node is None:
            return None

        adapter = await self._panels.for_node(node)
        readings = await adapter.bulk_usage([_ref_for(subscription)])
        usage = readings.get(subscription.remote_username)
        if usage is None:
            return subscription

        subscription.record_usage(
            used_mib=usage.used_bytes // BYTES_PER_MIB,
            at=usage.measured_at,
            online_at=usage.online_at,
        )
        await self._subscriptions.update(subscription)
        return subscription

    async def sync_all(self, *, batch_size: int = 500) -> SyncReport:
        """One batched request per node holding accounts, for the scheduled job.

        Driven by where subscriptions actually are, not by `list_sellable()`.
        That answers "where would a new account go", and a node the operator
        stopped selling from - full, draining, in maintenance - still has
        paying customers whose usage has to keep moving. Under the old query
        their figure froze the moment the flag flipped, and because every quota
        warning is computed from that figure, their 80% notice stopped firing
        too.
        """
        report = SyncReport()
        for node_id in await self._subscriptions.node_ids_with_accounts():
            report.nodes.append(await self.sync_node(node_id, batch_size=batch_size))
        return report

    async def sync_node(self, node_id: str, *, batch_size: int = 500) -> NodeSyncReport:
        node = await self._nodes.get(node_id)
        if node is None:
            return NodeSyncReport(node_id=node_id, error="Unknown node.")

        subscriptions, _ = await self._subscriptions.search(
            node_id=node_id, limit=batch_size, offset=0
        )
        syncable = [s for s in subscriptions if s.remote_username]
        if not syncable:
            return NodeSyncReport(node_id=node_id)

        try:
            adapter = await self._panels.for_node(node)
            readings = await adapter.bulk_usage([_ref_for(s) for s in syncable])
        except Exception as exc:
            # Deliberately swallowed: the next node still deserves its turn.
            #
            # `Exception`, not `PanelError`. Building the adapter decrypts the
            # stored password and validates the config payload, and neither of
            # those failures is a PanelError - so a single node with a rotated
            # key or a malformed config took down the whole sweep, silently,
            # under a `worker.tick_failed` that names no node.
            return NodeSyncReport(
                node_id=node_id,
                skipped=len(syncable),
                error=f"{type(exc).__name__}: {exc}",
            )

        updated = 0
        for subscription in syncable:
            usage = readings.get(subscription.remote_username or "")
            if usage is None:
                continue
            subscription.record_usage(
                used_mib=usage.used_bytes // BYTES_PER_MIB,
                at=usage.measured_at,
                online_at=usage.online_at,
            )
            await self._subscriptions.update(subscription)
            updated += 1

        return NodeSyncReport(node_id=node_id, updated=updated, skipped=len(syncable) - updated)


def _ref_for(subscription: Subscription) -> PanelAccountRef:
    from geekvpn.application.provisioning.provisioning_service import panel_id_for

    return PanelAccountRef(
        panel_id=panel_id_for(subscription.node_id or ""),
        username=subscription.remote_username or "",
        external_id=subscription.remote_id,
    )


__all__ = [
    "BYTES_PER_MIB",
    "NodeSyncReport",
    "SyncReport",
    "UsageSyncService",
]
