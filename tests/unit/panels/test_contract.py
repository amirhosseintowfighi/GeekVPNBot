"""Cross-adapter conformance suite.

Every adapter is run against the SAME behavioural expectations. This is what
makes the abstraction trustworthy: without it, "implements the interface"
means only that the method names match, and each panel drifts into its own
subtly different semantics until the business layer needs to know which panel
it is talking to - which is precisely the coupling we are paying this
architecture to avoid.

Adding a new adapter automatically enrols it here, because the suite is
parametrised over the registry rather than a hand-written list.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from geekvpn.domain.panels.enums import Capability, PanelKind
from geekvpn.domain.panels.errors import (
    AccountNotFound,
    CapabilityNotSupported,
    PanelAuthFailed,
    PanelError,
    PanelUnreachable,
)
from geekvpn.domain.panels.values import AccountSpec, TrafficQuota
from geekvpn.infrastructure.panels.factory import PanelFactory
from geekvpn.infrastructure.panels.registry import load_bundled_adapters, registry
from tests.panel_fakes import PANEL_ID, FakePanelServer

load_bundled_adapters()

EXPIRY = datetime(2026, 12, 1, tzinfo=UTC)

#: Minimum viable config per panel. The x-ui family needs an inbound id.
_CONFIGS: dict[PanelKind, dict[str, object]] = {
    PanelKind.PASARGUARD: {},
    PanelKind.MARZBAN: {},
    PanelKind.MARZNESHIN: {},
    PanelKind.SANAEI: {"inbound_id": 1},
    PanelKind.ALIREZA: {"inbound_id": 1},
}

ALL_KINDS = sorted(registry.kinds, key=lambda k: k.value)


def build(kind: PanelKind, server: FakePanelServer, **overrides: object) -> object:
    payload: dict[str, object] = {
        "base_url": "https://panel.test",
        "username": "admin",
        "password": "secret",
        "max_attempts": 1,
        **_CONFIGS[kind],
        **overrides,
    }
    return PanelFactory().build(kind, payload, panel_id=PANEL_ID, transport=server.transport)


def spec(username: str = "cust-1") -> AccountSpec:
    return AccountSpec(
        username=username,
        quota=TrafficQuota.from_gib(30),
        expires_at=EXPIRY,
    )


@pytest.mark.parametrize("kind", ALL_KINDS, ids=lambda k: k.value)
def test_the_factory_can_build_every_registered_panel(kind: PanelKind) -> None:
    """The factory contains no panel-specific code; prove it works for all."""
    adapter = build(kind, FakePanelServer())
    assert adapter.kind is kind


@pytest.mark.parametrize("kind", ALL_KINDS, ids=lambda k: k.value)
def test_config_validation_rejects_a_bad_base_url(kind: PanelKind) -> None:
    from geekvpn.domain.base.errors import ValidationError

    with pytest.raises(ValidationError):
        PanelFactory().validate_config(kind, {"base_url": "not-a-url", **_CONFIGS[kind]})


@pytest.mark.parametrize("kind", ALL_KINDS, ids=lambda k: k.value)
@pytest.mark.asyncio
async def test_health_never_raises_even_when_the_panel_is_down(
    kind: PanelKind,
) -> None:
    """Health is called by the scheduler across every panel. One dead panel
    must not raise an exception that aborts the sweep for the others."""

    def explode(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    server = FakePanelServer()
    server.prefix("GET", "/", handler=explode)
    server.prefix("POST", "/", handler=explode)
    adapter = build(kind, server)

    result = await adapter.health()

    assert result.is_healthy is False
    assert result.message


@pytest.mark.parametrize("kind", ALL_KINDS, ids=lambda k: k.value)
@pytest.mark.asyncio
async def test_transport_failures_surface_as_panel_errors(kind: PanelKind) -> None:
    """No raw httpx exception may escape an adapter.

    The saga layer dispatches on our error taxonomy; an httpx exception would
    fall through as an unhandled 500 and strand a paid order.
    """

    def explode(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    server = FakePanelServer()
    server.prefix("GET", "/", handler=explode)
    server.prefix("POST", "/", handler=explode)
    adapter = build(kind, server)

    with pytest.raises(PanelError) as excinfo:
        await adapter.create_account(spec(), idempotency_key="k1")
    assert isinstance(excinfo.value, PanelUnreachable)
    assert excinfo.value.retryable is True


@pytest.mark.parametrize("kind", ALL_KINDS, ids=lambda k: k.value)
@pytest.mark.asyncio
async def test_rejected_credentials_are_terminal_not_retryable(
    kind: PanelKind,
) -> None:
    """Retrying a 401 is how a platform gets its IP banned by every panel."""
    server = FakePanelServer()
    server.prefix("POST", "/", status=401, json={"detail": "bad credentials"})
    server.prefix("GET", "/", status=401, json={"detail": "bad credentials"})
    adapter = build(kind, server, max_attempts=3)

    with pytest.raises(PanelAuthFailed) as excinfo:
        await adapter.create_account(spec(), idempotency_key="k1")

    assert excinfo.value.retryable is False
    # Exactly one attempt: no retry storm against a panel that said "no".
    assert len(server.calls) == 1


@pytest.mark.parametrize("kind", ALL_KINDS, ids=lambda k: k.value)
@pytest.mark.asyncio
async def test_unsupported_capabilities_raise_a_typed_error(
    kind: PanelKind,
) -> None:
    """Calling an unsupported capability must be an explicit, typed refusal -
    never a silent no-op that leaves a subscription half-configured."""
    adapter = build(kind, FakePanelServer())
    plugin = registry.get(kind)

    if Capability.NODE_INVENTORY not in plugin.capabilities:
        with pytest.raises(CapabilityNotSupported):
            await adapter.nodes()
    if Capability.BULK_USAGE not in plugin.capabilities:
        with pytest.raises(CapabilityNotSupported):
            await adapter.bulk_usage([])
    if Capability.SUBSCRIPTION_URL not in plugin.capabilities:
        with pytest.raises(CapabilityNotSupported):
            await adapter.subscription(adapter.ref("x"))


@pytest.mark.parametrize("kind", ALL_KINDS, ids=lambda k: k.value)
@pytest.mark.asyncio
async def test_deleting_an_absent_account_succeeds(kind: PanelKind) -> None:
    """A retried delete is indistinguishable from a first delete.

    Compensating transactions retry, so a delete that raises on "already gone"
    would wedge every rollback permanently.
    """
    server = FakePanelServer()
    _install_auth(server, kind)
    server.prefix("DELETE", "/", status=404, json={"detail": "not found"})
    server.prefix("GET", "/", status=404, json={"detail": "not found"})
    server.prefix("POST", "/panel/api", json={"success": True, "obj": {"settings": "{}"}})
    server.prefix("POST", "/xui/API", json={"success": True, "obj": {"settings": "{}"}})
    adapter = build(kind, server)

    # Must not raise.
    await adapter.delete_account(adapter.ref("ghost"), idempotency_key="k1")


@pytest.mark.parametrize("kind", ALL_KINDS, ids=lambda k: k.value)
@pytest.mark.asyncio
async def test_a_missing_account_raises_account_not_found(kind: PanelKind) -> None:
    server = FakePanelServer()
    _install_auth(server, kind)
    if kind in (PanelKind.SANAEI, PanelKind.ALIREZA):
        # Inbound exists but holds no matching client.
        server.prefix(
            "GET",
            "/panel/api/inbounds/get",
            json={"success": True, "obj": {"settings": '{"clients": []}'}},
        )
        server.prefix(
            "GET",
            "/xui/API/inbounds/get",
            json={"success": True, "obj": {"settings": '{"clients": []}'}},
        )
    else:
        server.prefix("GET", "/api", status=404, json={"detail": "not found"})
    adapter = build(kind, server)

    with pytest.raises(AccountNotFound):
        await adapter.get_account(adapter.ref("ghost"))


@pytest.mark.parametrize("kind", ALL_KINDS, ids=lambda k: k.value)
@pytest.mark.asyncio
async def test_close_is_safe_to_call_twice(kind: PanelKind) -> None:
    adapter = build(kind, FakePanelServer())
    await adapter.close()
    await adapter.close()


def _install_auth(server: FakePanelServer, kind: PanelKind) -> None:
    """Install whichever login endpoint this panel family uses."""
    server.route("POST", "/api/admin/token", json={"access_token": "t", "token_type": "bearer"})
    server.route("POST", "/api/admins/token", json={"access_token": "t", "token_type": "bearer"})
    server.route("POST", "/login", json={"success": True, "msg": "ok"})
