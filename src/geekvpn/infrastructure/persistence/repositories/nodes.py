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
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.application.provisioning.ports import NodeAdminRecord, NodeRecord
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


def node_to_admin_record(model: NodeModel) -> NodeAdminRecord:
    """Project a row onto the operator-facing shape. Still drops the password."""
    timeout = model.timeout_seconds
    return NodeAdminRecord(
        id=model.id,
        name_fa=model.name_fa,
        panel_kind=PanelKind(model.panel_kind),
        state=NodeState(model.state),
        base_url=model.base_url,
        username=model.username,
        has_password=bool(model.password_encrypted),
        verify_tls=model.verify_tls,
        # Numeric() hands back a Decimal at runtime even though the column is
        # declared float, so the cast is real however the checker sees it.
        timeout_seconds=float(timeout),
        capacity=model.capacity,
        account_count=model.account_count,
        accepting_new=model.accepting_new,
        country_code=model.country_code,
        sort_order=model.sort_order,
        last_check_at=model.last_check_at,
        last_error=model.last_error,
    )


#: Request fields whose column name differs, kept in one place so `update` stays
#: a loop rather than a wall of `if`.
_COLUMN_ALIASES: dict[str, str] = {"password": "password_encrypted"}


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
            "timeout_seconds": float(timeout),
        }
        return row.panel_kind, payload

    # -- administration ----------------------------------------------------
    #
    # Operators need to see and edit the connection settings that selection is
    # deliberately kept away from, so these return `NodeAdminRecord`. None of
    # them ever returns the password.

    async def list_all(self) -> Sequence[NodeAdminRecord]:
        stmt = select(NodeModel).order_by(NodeModel.sort_order, NodeModel.id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [node_to_admin_record(row) for row in rows]

    async def get_for_admin(self, node_id: str) -> NodeAdminRecord | None:
        row = await self._session.get(NodeModel, node_id)
        return node_to_admin_record(row) if row else None

    async def create(
        self,
        *,
        node_id: str,
        name_fa: str,
        panel_kind: PanelKind,
        base_url: str,
        username: str,
        password: str,
        country_code: str | None,
        capacity: int,
        verify_tls: bool,
        timeout_seconds: float,
        sort_order: int,
        config: dict[str, object] | None = None,
    ) -> NodeAdminRecord:
        row = NodeModel(
            id=node_id,
            name_fa=name_fa,
            panel_kind=panel_kind.value,
            base_url=base_url,
            username=username,
            password_encrypted=password,
            country_code=country_code,
            capacity=capacity,
            verify_tls=verify_tls,
            timeout_seconds=timeout_seconds,
            sort_order=sort_order,
            config_json=config or {},
            state=NodeState.ONLINE.value,
            accepting_new=True,
            account_count=0,
        )
        self._session.add(row)
        await self._session.flush()
        return node_to_admin_record(row)

    async def update(self, node_id: str, **changes: object) -> NodeAdminRecord | None:
        """Apply only the fields the caller actually sent.

        A password of ``None`` means "leave it alone", which is what lets the
        admin panel round-trip a node it was never shown the password for.
        """
        row = await self._session.get(NodeModel, node_id)
        if row is None:
            return None
        for field, value in changes.items():
            if value is None:
                continue
            setattr(row, _COLUMN_ALIASES.get(field, field), value)
        await self._session.flush()
        return node_to_admin_record(row)

    async def delete(self, node_id: str) -> bool:
        row = await self._session.get(NodeModel, node_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    async def record_check(self, node_id: str, *, at: datetime, error: str | None) -> None:
        """Store the outcome of a connection test so the list view can show it."""
        row = await self._session.get(NodeModel, node_id)
        if row is not None:
            row.last_check_at = at
            row.last_error = error
            await self._session.flush()

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


__all__ = ["SqlAlchemyNodeRepository", "node_to_admin_record", "node_to_record"]
