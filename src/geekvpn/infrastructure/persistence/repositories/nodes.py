"""The node repository.

Returns :class:`NodeRecord` rather than the SQLAlchemy model on purpose. Node
selection is a pure function over a handful of numbers, and handing it an ORM
row would drag the panel password through a decision that has no business
seeing it - as well as making the selector untestable without a database.

The credentials are fetched separately, by id, only at the moment an adapter is
actually being built. That is the difference between "the selector knows which
node" and "the selector knows the password".
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.application.provisioning.ports import NodeRecord
from geekvpn.domain.panels.enums import PanelKind
from geekvpn.domain.provisioning.enums import NodeState
from geekvpn.infrastructure.persistence.models.provisioning import NodeModel


def node_to_record(model: NodeModel) -> NodeRecord:
    """Project a row onto the shape the selector needs. Drops the credentials."""
    return NodeRecord(
        id=model.id,
        name_fa=model.name_fa,
        panel_kind=PanelKind(model.panel_kind),
        state=NodeState(model.state),
        accepting_new=model.accepting_new,
        capacity=model.capacity,
        account_count=model.account_count,
        country_code=model.country_code,
        sort_order=model.sort_order,
    )


class SqlAlchemyNodeRepository:
    """Reads nodes. Never commits; the unit of work owns the transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, node_id: str) -> NodeRecord | None:
        row = await self._session.get(NodeModel, node_id)
        return node_to_record(row) if row else None

    async def list_sellable(self) -> Sequence[NodeRecord]:
        """Every node that could conceivably take a new account.

        The final decision stays in :func:`select_node`. This filters only on
        what an index can answer - the ``ix_nodes_sellable`` partial index from
        migration 0005 - so a full node is still returned and rejected in one
        readable place rather than disappearing into a WHERE clause.
        """
        stmt = (
            select(NodeModel)
            .where(
                NodeModel.state == NodeState.ONLINE.value,
                NodeModel.accepting_new.is_(True),
            )
            .order_by(NodeModel.sort_order, NodeModel.id)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [node_to_record(row) for row in rows]

    async def credentials_for(self, node_id: str) -> tuple[str, dict[str, object]] | None:
        """The panel kind and the full adapter config payload for one node.

        Returns ``None`` when the node has no password. A node without
        credentials is not a node with empty credentials: attempting to log in
        with an empty password produces a confusing 401 from someone else's
        panel instead of a clear configuration error from ours.
        """
        row = await self._session.get(NodeModel, node_id)
        if row is None or not row.password_encrypted:
            return None

        timeout = row.timeout_seconds
        payload: dict[str, object] = {
            **dict(row.config_json or {}),
            "base_url": row.base_url,
            "username": row.username,
            "password": row.password_encrypted,
            "verify_tls": row.verify_tls,
            "timeout_seconds": float(timeout) if isinstance(timeout, Decimal) else timeout,
        }
        return row.panel_kind, payload

    async def record_account_added(self, node_id: str) -> None:
        """Increment the load counter after a successful create.

        Kept as an explicit call rather than a trigger so that a create which
        succeeded on the panel but failed to commit here does not leave the
        counter permanently ahead of reality; the periodic sync corrects it.
        """
        row = await self._session.get(NodeModel, node_id)
        if row is not None:
            row.account_count += 1
            await self._session.flush()


__all__ = ["SqlAlchemyNodeRepository", "node_to_record"]
