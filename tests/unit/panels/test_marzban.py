"""Marzban adapter behaviour."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from geekvpn.domain.panels.enums import AccountState, Capability, PanelKind
from geekvpn.domain.panels.errors import CapabilityNotSupported
from geekvpn.domain.panels.values import AccountSpec, TrafficQuota
from geekvpn.infrastructure.panels.factory import PanelFactory
from geekvpn.infrastructure.panels.registry import registry
from tests.panel_fakes import PANEL_ID, FakePanelServer

EXPIRY = datetime(2026, 12, 1, tzinfo=UTC)
GIB = 1024**3


def build(server: FakePanelServer, **cfg: object) -> object:
    return PanelFactory().build(
        PanelKind.MARZBAN,
        {
            "base_url": "https://panel.test",
            "username": "admin",
            "password": "secret",
            "max_attempts": 1,
            **cfg,
        },
        panel_id=PANEL_ID,
        transport=server.transport,
    )


def with_auth(server: FakePanelServer) -> FakePanelServer:
    return server.route(
        "POST", "/api/admin/token", json={"access_token": "t", "token_type": "bearer"}
    )


def user_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "username": "cust-1",
        "status": "active",
        "used_traffic": 0,
        "data_limit": 30 * GIB,
        "expire": int(EXPIRY.timestamp()),
        "subscription_url": "/sub/xyz",
        "links": [],
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_create_requests_the_configured_inbounds_per_protocol() -> None:
    """Marzban keys inbounds by protocol; a flat list is silently ignored."""
    captured: dict[str, object] = {}

    def create(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.read()))
        return httpx.Response(200, json=user_payload())

    server = with_auth(FakePanelServer()).route("POST", "/api/user", handler=create)
    adapter = build(server, default_inbounds={"vless": ["VLESS_TCP"]})

    await adapter.create_account(
        AccountSpec(username="cust-1", quota=TrafficQuota.from_gib(30), expires_at=EXPIRY),
        idempotency_key="k1",
    )

    assert captured["inbounds"] == {"vless": ["VLESS_TCP"]}
    assert "proxies" in captured


@pytest.mark.asyncio
async def test_unlimited_quota_is_sent_as_zero_not_null() -> None:
    """Marzban treats null as 'no change'; only 0 means unlimited."""
    captured: dict[str, object] = {}

    def create(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.read()))
        return httpx.Response(200, json=user_payload(data_limit=0))

    server = with_auth(FakePanelServer()).route("POST", "/api/user", handler=create)

    account = await build(server).create_account(
        AccountSpec(username="cust-1", quota=TrafficQuota(None), expires_at=None),
        idempotency_key="k1",
    )

    assert captured["data_limit"] == 0
    assert captured["expire"] == 0
    assert account.usage.quota.is_unlimited


@pytest.mark.asyncio
async def test_suspend_sets_the_disabled_status() -> None:
    captured: dict[str, object] = {}

    def modify(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.read()))
        return httpx.Response(200, json=user_payload(status="disabled"))

    server = with_auth(FakePanelServer()).prefix("PUT", "/api/user/", handler=modify)
    adapter = build(server)

    account = await adapter.suspend(adapter.ref("cust-1"), idempotency_key="k1")

    assert captured["status"] == "disabled"
    assert account.state is AccountState.SUSPENDED


def test_marzban_does_not_claim_per_node_assignment() -> None:
    """Marzban has no per-user node pinning; claiming it would break routing."""
    plugin = registry.get(PanelKind.MARZBAN)
    assert Capability.PER_NODE_ASSIGNMENT not in plugin.capabilities


@pytest.mark.asyncio
async def test_device_limit_is_refused_rather_than_silently_dropped() -> None:
    """Selling a 3-device plan on a panel that cannot enforce it is fraud."""
    adapter = build(FakePanelServer())
    with pytest.raises(CapabilityNotSupported):
        adapter.require(Capability.DEVICE_LIMIT)
