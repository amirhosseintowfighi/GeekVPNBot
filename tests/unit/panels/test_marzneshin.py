"""Marzneshin adapter behaviour.

The interesting cases are all places where Marzneshin diverges from its Marzban
ancestor: services instead of inbounds, ISO dates instead of epochs, explicit
enable/disable verbs, and a paginated `items` envelope.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from geekvpn.domain.panels.enums import AccountState, PanelKind
from geekvpn.domain.panels.values import AccountSpec, TrafficQuota
from geekvpn.infrastructure.panels.factory import PanelFactory
from tests.panel_fakes import PANEL_ID, FakePanelServer

EXPIRY = datetime(2026, 12, 1, tzinfo=UTC)
GIB = 1024**3


def build(server: FakePanelServer, **cfg: object) -> object:
    return PanelFactory().build(
        PanelKind.MARZNESHIN,
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
        "POST", "/api/admins/token", json={"access_token": "t", "token_type": "bearer"}
    )


def user_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "username": "cust-1",
        "enabled": True,
        "expired": False,
        "data_limit_reached": False,
        "used_traffic": 2 * GIB,
        "data_limit": 50 * GIB,
        "expire_date": EXPIRY.isoformat(),
        "subscription_url": "https://panel.test/sub/zzz",
        "service_ids": [1, 2],
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_create_uses_service_ids_and_an_iso_expiry() -> None:
    """Marzneshin rejects epoch expiries and ignores inbound tags."""
    captured: dict[str, object] = {}

    def create(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.read()))
        return httpx.Response(200, json=user_payload())

    server = with_auth(FakePanelServer()).route("POST", "/api/users", handler=create)
    adapter = build(server, service_ids=[7, 9])

    await adapter.create_account(
        AccountSpec(username="cust-1", quota=TrafficQuota.from_gib(50), expires_at=EXPIRY),
        idempotency_key="k1",
    )

    assert captured["service_ids"] == [7, 9]
    assert captured["expire_strategy"] == "fixed_date"
    assert captured["expire_date"] == EXPIRY.isoformat()


@pytest.mark.asyncio
async def test_an_account_with_no_expiry_uses_the_never_strategy() -> None:
    captured: dict[str, object] = {}

    def create(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.read()))
        return httpx.Response(200, json=user_payload(expire_date=None))

    server = with_auth(FakePanelServer()).route("POST", "/api/users", handler=create)

    await build(server).create_account(
        AccountSpec(username="cust-1", quota=TrafficQuota(None), expires_at=None),
        idempotency_key="k1",
    )

    assert captured["expire_strategy"] == "never"
    assert "expire_date" not in captured


@pytest.mark.asyncio
async def test_suspend_calls_the_disable_verb_then_rereads() -> None:
    """The verb endpoints return no body, so the adapter must re-read to
    report truthful state rather than guessing."""
    server = with_auth(FakePanelServer())
    server.route("POST", "/api/users/cust-1/disable", status=204)
    server.route("GET", "/api/users/cust-1", json=user_payload(enabled=False))
    adapter = build(server)

    account = await adapter.suspend(adapter.ref("cust-1"), idempotency_key="k1")

    assert "/api/users/cust-1/disable" in server.paths("POST")
    assert account.state is AccountState.SUSPENDED


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"expired": True}, AccountState.EXPIRED),
        ({"data_limit_reached": True}, AccountState.QUOTA_EXHAUSTED),
        ({"enabled": False}, AccountState.SUSPENDED),
        ({}, AccountState.ACTIVE),
    ],
)
@pytest.mark.asyncio
async def test_the_specific_reason_for_being_offline_is_preserved(
    payload: dict[str, object], expected: AccountState
) -> None:
    """'Expired' and 'out of data' need different messages to the customer,
    so collapsing both into 'inactive' would make the bot unhelpful."""
    server = with_auth(FakePanelServer())
    server.route("GET", "/api/users/cust-1", json=user_payload(**payload))
    adapter = build(server)

    account = await adapter.get_account(adapter.ref("cust-1"))

    assert account.state is expected


@pytest.mark.asyncio
async def test_bulk_usage_reads_the_paginated_items_envelope() -> None:
    server = with_auth(FakePanelServer())
    server.route(
        "GET",
        "/api/users",
        json={
            "items": [
                user_payload(username="cust-1"),
                user_payload(username="cust-2", used_traffic=9 * GIB),
            ],
            "total": 2,
        },
    )
    adapter = build(server)

    usage = await adapter.bulk_usage([adapter.ref("cust-1"), adapter.ref("cust-2")])

    assert usage["cust-2"].used_bytes == 9 * GIB


@pytest.mark.asyncio
async def test_bulk_usage_with_no_refs_makes_no_request() -> None:
    """The nightly sweep runs per panel; an empty batch must not hit the API."""
    server = with_auth(FakePanelServer())
    adapter = build(server)

    assert await adapter.bulk_usage([]) == {}
    assert server.calls == []
