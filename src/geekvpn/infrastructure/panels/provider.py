"""Turning a selected node into a live panel adapter.

This is the last missing link of Phase 3. The factory could always build an
adapter from a config payload; nothing ever fetched that payload from the
database, so five working adapters were unreachable code.

Two behaviours here are deliberate and worth defending:

**Adapters are cached per node for the life of the provider.** Each adapter owns
an ``httpx`` client with a connection pool, and building a fresh one per order
throws away every keep-alive connection and re-authenticates against the panel
on every purchase. The provider is request-scoped, so the cache cannot outlive
the credentials it was built from.

**A node without credentials raises rather than returning something broken.**
An adapter built with an empty password produces a 401 from somebody else's
panel, several seconds later, attributed to the wrong cause. Failing here names
the actual problem: the node is not configured.
"""

from __future__ import annotations

from typing import Any

from geekvpn.application.provisioning.ports import NodeRecord
from geekvpn.application.provisioning.provisioning_service import panel_id_for
from geekvpn.domain.panels.errors import PanelAuthFailed
from geekvpn.infrastructure.panels.factory import PanelFactory
from geekvpn.infrastructure.persistence.repositories.nodes import (
    SqlAlchemyNodeRepository,
)


class DatabasePanelProvider:
    """Builds adapters from stored node credentials."""

    __slots__ = ("_cache", "_factory", "_nodes")

    def __init__(
        self,
        *,
        nodes: SqlAlchemyNodeRepository,
        factory: PanelFactory | None = None,
    ) -> None:
        self._nodes = nodes
        self._factory = factory or PanelFactory()
        self._cache: dict[str, Any] = {}

    async def for_node(self, node: NodeRecord) -> Any:
        """Return a live :class:`PanelAdapter` for ``node``.

        :raises PanelAuthFailed: the node has no stored password.
        """
        cached = self._cache.get(node.id)
        if cached is not None:
            return cached

        credentials = await self._nodes.credentials_for(node.id)
        if credentials is None:
            raise PanelAuthFailed(
                "This server has no stored credentials.",
                panel=node.panel_kind.value,
                node_id=node.id,
            )

        kind, payload = credentials
        adapter = self._factory.build(kind, payload, panel_id=panel_id_for(node.id))
        self._cache[node.id] = adapter
        return adapter

    async def aclose(self) -> None:
        """Release every pooled connection. Called when the scope ends."""
        for adapter in self._cache.values():
            await adapter.close()
        self._cache.clear()


__all__ = ["DatabasePanelProvider"]
