"""Optional composable helper for HTTP adapters.

Deliberately NOT a mandatory base class. `PanelAdapter` is a `Protocol`, so an
adapter is free to ignore all of this - which matters the day someone needs to
integrate a panel that speaks SSH or gRPC.

What lives here is only what is genuinely identical across HTTP panels:
capability gating, bearer-token caching, and the unsupported-operation
fallbacks. Anything panel-specific belongs in the adapter.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from geekvpn.domain.panels.enums import Capability, PanelKind, SubscriptionFormat
from geekvpn.domain.panels.errors import CapabilityNotSupported
from geekvpn.domain.panels.values import (
    AccountUsage,
    NodeInfo,
    PanelAccountRef,
    PanelGroup,
    SubscriptionPayload,
)
from geekvpn.infrastructure.panels.http import PanelHttpClient

#: Refresh a panel token this long before it actually expires, so a request is
#: never issued with a token that dies mid-flight.
TOKEN_REFRESH_MARGIN = timedelta(seconds=60)
#: Assumed lifetime when a panel does not tell us. Conservative on purpose.
DEFAULT_TOKEN_TTL = timedelta(minutes=30)


class HttpPanelAdapter:
    """Shared plumbing for token-authenticated HTTP panels."""

    kind: ClassVar[PanelKind]
    capabilities: ClassVar[frozenset[Capability]] = frozenset()

    def __init__(self, *, config: Any, client: PanelHttpClient, panel_id: uuid.UUID) -> None:
        # The factory has always passed panel_id; the constructor never accepted it,
        # so every adapter construction through the factory raised TypeError. The
        # id is required rather than optional because an account reference that
        # does not say which panel it lives on cannot be acted on later: renewals
        # and suspensions have to reach the same server that issued the account.
        self._config = config
        self._http = client
        self._panel_id = panel_id
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    @property
    def panel_id(self) -> uuid.UUID:
        """Which panel row this adapter speaks for."""
        return self._panel_id

    def ref(
        self,
        username: str,
        *,
        external_id: str | None = None,
        container_id: str | None = None,
    ) -> PanelAccountRef:
        """Build a reference to an account on *this* panel.

        Every adapter needs this and each was calling ``self.ref(...)`` already;
        the helper simply did not exist, so the id was threaded no further than
        the constructor. Centralising it here means an adapter cannot accidentally
        stamp a reference with the wrong panel: renewals and suspensions must
        reach the same server that issued the account.
        """
        return PanelAccountRef(
            panel_id=self._panel_id,
            username=username,
            external_id=external_id,
            container_id=container_id,
        )

    # -- capability gate ---------------------------------------------------

    async def groups(self) -> Sequence[PanelGroup]:
        """No groups, unless an adapter says otherwise.

        Every panel this project speaks to grants access *somehow* - Marzban
        through inbounds, Marzneshin through services - but only PasarGuard can
        list them, and only a list is useful for choosing between them. So the
        default is an honest refusal rather than an empty list, which would
        read on screen as "this panel has none configured".
        """
        self.require(Capability.ACCESS_GROUPS)
        return ()

    def require(self, capability: Capability) -> None:
        """Guard a capability-gated method.

        Raising here rather than returning a soft failure is intentional: a
        caller that skipped the `capabilities` check has a bug, and a loud
        error in staging beats a silently unrenewed subscription in production.
        """
        if capability not in self.capabilities:
            raise CapabilityNotSupported(
                f"{self.kind.value} does not support {capability.value}.",
                panel=self.kind.value,
                capability=capability.value,
            )

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    # -- token cache -------------------------------------------------------

    async def _bearer(self) -> str:
        """Return a live token, logging in only when necessary."""
        now = datetime.now(UTC)
        if (
            self._token is not None
            and self._token_expires_at is not None
            and now + TOKEN_REFRESH_MARGIN < self._token_expires_at
        ):
            return self._token
        token, ttl = await self._login()
        self._token = token
        self._token_expires_at = now + (ttl or DEFAULT_TOKEN_TTL)
        return token

    async def _login(self) -> tuple[str, timedelta | None]:  # pragma: no cover
        raise NotImplementedError

    async def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._bearer()}"}

    def _invalidate_token(self) -> None:
        self._token = None
        self._token_expires_at = None

    # -- lifecycle ---------------------------------------------------------

    async def close(self) -> None:
        await self._http.close()

    # -- capability-gated defaults ----------------------------------------
    # Adapters that DO support these override them. The default implementation
    # raises, so an unimplemented capability can never silently no-op.

    async def reset_traffic(self, ref: PanelAccountRef, *, idempotency_key: str) -> Any:
        self.require(Capability.RESET_TRAFFIC)
        raise NotImplementedError  # pragma: no cover

    async def bulk_usage(self, refs: Sequence[PanelAccountRef]) -> Mapping[str, AccountUsage]:
        self.require(Capability.BULK_USAGE)
        raise NotImplementedError  # pragma: no cover

    async def nodes(self) -> Sequence[NodeInfo]:
        self.require(Capability.NODE_INVENTORY)
        raise NotImplementedError  # pragma: no cover

    async def subscription(
        self, ref: PanelAccountRef, *, fmt: SubscriptionFormat = SubscriptionFormat.AUTO
    ) -> SubscriptionPayload:
        self.require(Capability.SUBSCRIPTION_URL)
        raise NotImplementedError  # pragma: no cover
