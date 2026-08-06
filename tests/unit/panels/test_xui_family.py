"""3x-ui (Sanaei) and x-ui (Alireza).

Both are driven through the same tests, parametrised over the two kinds, which
is the proof that the shared template base really does serve both. The only
thing asserted per-kind is the URL prefix.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from geekvpn.domain.panels.enums import AccountState, PanelKind
from geekvpn.domain.panels.errors import AccountNotFound, PanelContractViolation
from geekvpn.domain.panels.values import AccountSpec, TrafficQuota
from geekvpn.infrastructure.panels.factory import PanelFactory
from tests.panel_fakes import PANEL_ID, FakePanelServer

EXPIRY = datetime(2026, 12, 1, tzinfo=UTC)
GIB = 1024**3

FAMILY = [
    pytest.param(PanelKind.SANAEI, "/panel/api/inbounds", id="sanaei"),
    pytest.param(PanelKind.ALIREZA, "/xui/API/inbounds", id="alireza"),
]


def build(kind: PanelKind, server: FakePanelServer, **cfg: object) -> object:
    return PanelFactory().build(
        kind,
        {
            "base_url": "https://panel.test",
            "username": "admin",
            "password": "secret",
            "inbound_id": 3,
            "max_attempts": 1,
            **cfg,
        },
        panel_id=PANEL_ID,
        transport=server.transport,
    )


def client(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "3f2b1c4d-0000-0000-0000-000000000001",
        "email": "cust-1",
        "enable": True,
        "totalGB": 30 * GIB,
        "expiryTime": int(EXPIRY.timestamp() * 1000),
        "limitIp": 2,
    }
    base.update(overrides)
    return base


def inbound(*clients: dict[str, object]) -> dict[str, object]:
    return {
        "success": True,
        "msg": "",
        "obj": {"id": 3, "settings": json.dumps({"clients": list(clients)})},
    }


def traffic(up: int = 1 * GIB, down: int = 2 * GIB, total: int = 30 * GIB) -> dict:
    return {"success": True, "obj": {"up": up, "down": down, "total": total}}


def with_auth(server: FakePanelServer) -> FakePanelServer:
    return server.route("POST", "/login", json={"success": True, "msg": "ok"})


@pytest.mark.parametrize(("kind", "prefix"), FAMILY)
@pytest.mark.asyncio
async def test_each_fork_talks_to_its_own_api_prefix(kind: PanelKind, prefix: str) -> None:
    """The single difference between these two adapters."""
    server = with_auth(FakePanelServer())
    server.prefix("GET", f"{prefix}/get", json=inbound(client()))
    server.prefix("GET", f"{prefix}/getClientTraffics", json=traffic())
    adapter = build(kind, server)

    await adapter.get_account(adapter.ref("cust-1"))

    assert any(p.startswith(prefix) for p in server.paths("GET"))


@pytest.mark.parametrize(("kind", "prefix"), FAMILY)
@pytest.mark.asyncio
async def test_login_uses_a_cookie_session_not_a_bearer_token(kind: PanelKind, prefix: str) -> None:
    """This family has no bearer tokens; sending one would be ignored at best."""
    server = with_auth(FakePanelServer())
    server.prefix("GET", f"{prefix}/get", json=inbound(client()))
    server.prefix("GET", f"{prefix}/getClientTraffics", json=traffic())
    adapter = build(kind, server)

    await adapter.get_account(adapter.ref("cust-1"))

    assert "/login" in server.paths("POST")
    for call in server.calls:
        assert "authorization" not in {k.lower() for k in call.headers}


@pytest.mark.parametrize(("kind", "prefix"), FAMILY)
@pytest.mark.asyncio
async def test_a_logical_failure_with_http_200_is_still_a_failure(
    kind: PanelKind, prefix: str
) -> None:
    """This family returns 200 with success=false.

    Trusting the status code alone would report a failed provisioning as a
    completed sale - the single most costly bug available in this integration.
    """
    server = with_auth(FakePanelServer())
    server.prefix(
        "GET",
        f"{prefix}/get",
        json={"success": False, "msg": "inbound not found", "obj": None},
    )
    adapter = build(kind, server)

    with pytest.raises(PanelContractViolation) as excinfo:
        await adapter.get_account(adapter.ref("cust-1"))

    assert "inbound not found" in str(excinfo.value)


@pytest.mark.parametrize(("kind", "prefix"), FAMILY)
@pytest.mark.asyncio
async def test_create_nests_the_client_inside_the_inbound(kind: PanelKind, prefix: str) -> None:
    """Clients are a JSON string inside the inbound, not a resource."""
    captured: dict[str, object] = {}

    exists = {"yet": False}

    def add(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.read()))
        exists["yet"] = True
        return httpx.Response(200, json={"success": True, "msg": "", "obj": None})

    def read_inbound(_request: httpx.Request) -> httpx.Response:
        # The idempotency pre-check and the post-create read hit the same URL. A
        # static route answered both with the client already present, so the
        # adapter correctly concluded the account existed and skipped addClient
        # entirely; the test then asserted on a request nobody had made.
        body = inbound(client()) if exists["yet"] else inbound()
        return httpx.Response(200, json=body)

    server = with_auth(FakePanelServer())
    # Registered before the shorter /get prefix, which would otherwise swallow it.
    server.prefix("GET", f"{prefix}/getClientTraffics", json=traffic())
    server.prefix("GET", f"{prefix}/get", handler=read_inbound)
    server.route("POST", f"{prefix}/addClient", handler=add)
    adapter = build(kind, server)

    await adapter.create_account(
        AccountSpec(username="cust-1", quota=TrafficQuota.from_gib(30), expires_at=EXPIRY),
        idempotency_key="k1",
    )

    assert captured["id"] == 3
    settings = json.loads(str(captured["settings"]))
    created = settings["clients"][0]
    # totalGB is a misnomer in this family: the field holds BYTES.
    assert created["totalGB"] == 30 * GIB
    # expiryTime is milliseconds, not seconds.
    assert created["expiryTime"] == int(EXPIRY.timestamp() * 1000)
    assert created["email"] == "cust-1"


@pytest.mark.parametrize(("kind", "prefix"), FAMILY)
@pytest.mark.asyncio
async def test_usage_is_the_sum_of_upload_and_download(kind: PanelKind, prefix: str) -> None:
    """Billing only the download would undercharge by roughly a third."""
    server = with_auth(FakePanelServer())
    server.prefix("GET", f"{prefix}/getClientTraffics", json=traffic(up=GIB, down=2 * GIB))
    adapter = build(kind, server)

    usage = await adapter.usage(adapter.ref("cust-1"))

    assert usage.used_bytes == 3 * GIB
    assert usage.quota.total_bytes == 30 * GIB
    assert usage.remaining_bytes == 27 * GIB


@pytest.mark.parametrize(("kind", "prefix"), FAMILY)
@pytest.mark.asyncio
async def test_a_disabled_client_reads_as_suspended(kind: PanelKind, prefix: str) -> None:
    server = with_auth(FakePanelServer())
    server.prefix("GET", f"{prefix}/get", json=inbound(client(enable=False)))
    server.prefix("GET", f"{prefix}/getClientTraffics", json=traffic())
    adapter = build(kind, server)

    account = await adapter.get_account(adapter.ref("cust-1"))

    assert account.state is AccountState.SUSPENDED


@pytest.mark.parametrize(("kind", "prefix"), FAMILY)
@pytest.mark.asyncio
async def test_a_missing_client_in_an_existing_inbound_is_not_found(
    kind: PanelKind, prefix: str
) -> None:
    server = with_auth(FakePanelServer())
    server.prefix("GET", f"{prefix}/get", json=inbound(client(email="someone-else")))
    adapter = build(kind, server)

    with pytest.raises(AccountNotFound):
        await adapter.get_account(adapter.ref("cust-1"))


@pytest.mark.parametrize(("kind", "prefix"), FAMILY)
@pytest.mark.asyncio
async def test_suspend_merges_onto_current_server_state(kind: PanelKind, prefix: str) -> None:
    """There is no partial update, so the whole client is resent.

    The merge must be onto freshly-read state, or a concurrent quota change
    made by an admin would be silently reverted.
    """
    captured: dict[str, object] = {}

    def update(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.read()))
        return httpx.Response(200, json={"success": True, "obj": None})

    server = with_auth(FakePanelServer())
    server.prefix("GET", f"{prefix}/get", json=inbound(client(totalGB=99 * GIB)))
    server.prefix("GET", f"{prefix}/getClientTraffics", json=traffic())
    server.prefix("POST", f"{prefix}/updateClient", handler=update)
    adapter = build(kind, server)

    await adapter.suspend(adapter.ref("cust-1"), idempotency_key="k1")

    sent = json.loads(str(captured["settings"]))["clients"][0]
    assert sent["enable"] is False
    # The admin's out-of-band quota bump survived our write.
    assert sent["totalGB"] == 99 * GIB
