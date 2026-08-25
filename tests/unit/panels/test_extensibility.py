"""The headline requirement: adding a panel must require ONLY a new adapter.

This test defines a brand-new panel entirely inside the test file - no edits to
the registry, the factory, the port, the domain, or any business logic - and
then drives it through the generic machinery. If anyone ever reintroduces a
hardcoded panel list or an `if kind == ...` branch, this test fails.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import ClassVar

import pytest

from geekvpn.application.ports.panel import PanelAdapter
from geekvpn.domain.panels.enums import AccountState, Capability
from geekvpn.domain.panels.errors import CapabilityNotSupported
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
from geekvpn.infrastructure.panels.config import PanelConnectionConfig
from geekvpn.infrastructure.panels.factory import PanelFactory
from geekvpn.infrastructure.panels.registry import PanelPlugin, PanelRegistry

PANEL_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")


class FictionalKind(StrEnum):
    """A panel that did not exist when the abstraction was designed."""

    HYPOTHETICAL = "hypothetical"


class HypotheticalConfig(PanelConnectionConfig):
    """Its own settings, with a field no other panel has."""

    region: str = "eu"


class HypotheticalAdapter:
    """A complete adapter written WITHOUT touching any shipped file.

    Note that it does not inherit from anything of ours - it satisfies the port
    structurally. That is the payoff of using a Protocol instead of an ABC: a
    third-party panel package never has to import our class hierarchy.
    """

    kind: ClassVar[FictionalKind] = FictionalKind.HYPOTHETICAL
    capabilities: ClassVar[frozenset[Capability]] = frozenset({Capability.RESET_TRAFFIC})

    def __init__(self, config: HypotheticalConfig, client: object, panel_id: uuid.UUID) -> None:
        self._config = config
        self._panel_id = panel_id
        self.store: dict[str, PanelAccount] = {}

    def ref(self, username: str, **kw: object) -> PanelAccountRef:
        return PanelAccountRef(panel_id=self._panel_id, username=username)

    async def health(self) -> PanelHealth:
        return PanelHealth(is_healthy=True, version=self._config.region)

    async def close(self) -> None:
        return None

    async def create_account(self, spec: AccountSpec, *, idempotency_key: str) -> PanelAccount:
        account = PanelAccount(
            ref=self.ref(spec.username),
            state=AccountState.ACTIVE,
            usage=AccountUsage(used_bytes=0, measured_at=datetime.now(tz=UTC_), quota=spec.quota),
            expires_at=spec.expires_at,
        )
        self.store[spec.username] = account
        return account

    async def get_account(self, ref: PanelAccountRef) -> PanelAccount:
        return self.store[ref.username]

    async def delete_account(self, ref: PanelAccountRef, *, idempotency_key: str) -> None:
        self.store.pop(ref.username, None)

    async def suspend(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        return self.store[ref.username]

    async def resume(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        return self.store[ref.username]

    async def usage(self, ref: PanelAccountRef) -> AccountUsage:
        return self.store[ref.username].usage

    async def renew(
        self,
        ref: PanelAccountRef,
        *,
        extend_by: timedelta | None = None,
        new_expires_at: datetime | None = None,
        new_quota: TrafficQuota | None = None,
        idempotency_key: str,
    ) -> PanelAccount:
        return self.store[ref.username]

    async def reset_traffic(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        return self.store[ref.username]

    async def bulk_usage(self, refs: Sequence[PanelAccountRef]) -> Mapping[str, AccountUsage]:
        raise NotImplementedError

    async def groups(self) -> Sequence[PanelGroup]:
        # Capability-gated like `reset_traffic` and `bulk_usage`: on the port
        # so a caller can always ask, and refused by adapters that cannot
        # answer. A panel that grants access some other way says so.
        raise CapabilityNotSupported("no groups", capability="access_groups")

    async def nodes(self) -> Sequence[NodeInfo]:
        raise NotImplementedError

    async def subscription(self, ref: PanelAccountRef, **kw: object) -> SubscriptionPayload:
        raise NotImplementedError


from datetime import UTC as UTC_  # noqa: E402  (kept local to this test module)


def test_a_brand_new_adapter_satisfies_the_port_without_inheriting_anything() -> None:
    adapter = HypotheticalAdapter(
        HypotheticalConfig(
            base_url="https://x.test",
            username="a",
            password="b",  # type: ignore[arg-type]
        ),
        client=None,
        panel_id=PANEL_ID,
    )
    assert isinstance(adapter, PanelAdapter)


@pytest.mark.asyncio
async def test_the_generic_machinery_drives_a_panel_it_has_never_heard_of() -> None:
    """Register, build and provision - with zero changes to shipped code."""
    isolated = PanelRegistry()
    isolated.register(
        PanelPlugin(
            kind=FictionalKind.HYPOTHETICAL,  # type: ignore[arg-type]
            adapter_cls=HypotheticalAdapter,
            config_cls=HypotheticalConfig,
            capabilities=HypotheticalAdapter.capabilities,
            description="A panel invented in a test.",
        )
    )

    factory = PanelFactory(panel_registry=isolated)
    adapter = factory.build(
        FictionalKind.HYPOTHETICAL,  # type: ignore[arg-type]
        {
            "base_url": "https://x.test",
            "username": "a",
            "password": "b",
            "region": "ir",
        },
        panel_id=PANEL_ID,
    )

    account = await adapter.create_account(
        AccountSpec(username="new-cust", quota=TrafficQuota.from_gib(10), expires_at=None),
        idempotency_key="k1",
    )

    assert account.state is AccountState.ACTIVE
    assert (await adapter.health()).version == "ir"
    assert isolated.get("hypothetical").adapter_cls is HypotheticalAdapter
