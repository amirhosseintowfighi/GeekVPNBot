"""WGDashboard: a WireGuard peer as a subscription.

Against a small stateful fake of the dashboard, so what is checked is the
peer the calls leave behind - its jobs, its restriction, its share link -
rather than which URLs were hit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from geekvpn.domain.panels.enums import AccountState, PanelKind
from geekvpn.domain.panels.errors import AccountNotFound
from geekvpn.domain.panels.values import AccountSpec, TrafficQuota
from geekvpn.infrastructure.panels.factory import PanelFactory
from tests.panel_fakes import PANEL_ID, FakePanelServer

pytestmark = pytest.mark.unit

GIB = 1024**3
EXPIRY = datetime(2026, 12, 1, tzinfo=UTC)


class Dashboard:
    """Just enough of WGDashboard v4 to hold peers, jobs and shares."""

    def __init__(self) -> None:
        self.peers: dict[str, dict[str, Any]] = {}
        self.restricted: set[str] = set()
        self.keys: list[str] = []
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        self.keys.append(request.headers.get("wg-dashboard-apikey", ""))
        body = json.loads(request.content) if request.content else {}
        if path == "/api/getWireguardConfigurationInfo":
            return self._ok(
                {
                    "configurationPeers": [
                        p for i, p in self.peers.items() if i not in self.restricted
                    ],
                    "configurationRestrictedPeers": [
                        p for i, p in self.peers.items() if i in self.restricted
                    ],
                }
            )
        if path == "/api/addPeers/wg0":
            peer_id = f"pub{len(self.peers)}="
            self.peers[peer_id] = {
                "id": peer_id,
                "name": body["name"],
                "total_receive": 0.0,
                "total_sent": 0.0,
                "jobs": [],
                "ShareLink": [],
            }
            return self._ok([self.peers[peer_id]])
        if path == "/api/savePeerScheduleJob":
            job = body["Job"]
            self.peers[job["Peer"]]["jobs"].append(job)
            return self._ok(None)
        if path == "/api/deletePeerScheduleJob":
            job = body["Job"]
            peer = self.peers[job["Peer"]]
            peer["jobs"] = [j for j in peer["jobs"] if j["JobID"] != job["JobID"]]
            return self._ok(None)
        if path == "/api/sharePeer/create":
            share = {"ShareID": f"share-{body['Peer']}", "ExpireDate": body["ExpireDate"]}
            self.peers[body["Peer"]]["ShareLink"].append(share)
            return self._ok([share])
        if path == "/api/restrictPeers/wg0":
            self.restricted.update(body["peers"])
            return self._ok(None)
        if path == "/api/allowAccessPeers/wg0":
            self.restricted.difference_update(body["peers"])
            return self._ok(None)
        if path == "/api/deletePeers/wg0":
            for peer_id in body["peers"]:
                self.peers.pop(peer_id, None)
            return self._ok(None)
        if path == "/api/resetPeerData/wg0":
            peer = self.peers[body["id"]]
            peer["total_receive"] = peer["total_sent"] = 0.0
            return self._ok(None)
        if path == "/api/handshake":
            return self._ok(None)
        return httpx.Response(404, json={"status": False, "message": "no such route"})

    @staticmethod
    def _ok(data: Any) -> httpx.Response:
        return httpx.Response(200, json={"status": True, "message": None, "data": data})

    def jobs(self, name: str) -> dict[str, str]:
        peer = next(p for p in self.peers.values() if p["name"] == name)
        return {job["Field"]: job["Value"] for job in peer["jobs"]}


def build(dashboard: Dashboard) -> Any:
    server = FakePanelServer()
    server.prefix("GET", "/api", handler=dashboard)
    server.prefix("POST", "/api", handler=dashboard)
    return PanelFactory().build(
        PanelKind.WGDASHBOARD,
        {
            "base_url": "https://wg.test",
            # Where the admin form puts it: the encrypted password column.
            "password": "secret-key",
            "configuration": "wg0",
            "max_attempts": 1,
        },
        panel_id=PANEL_ID,
        transport=server.transport,
    )


def spec(**overrides: Any) -> AccountSpec:
    fields: dict[str, Any] = {
        "username": "gv14050042",
        "quota": TrafficQuota.from_gib(30),
        "expires_at": EXPIRY,
    }
    fields.update(overrides)
    return AccountSpec(**fields)


@pytest.mark.asyncio
async def test_a_new_account_is_a_named_peer_with_its_limits_as_jobs() -> None:
    dashboard = Dashboard()

    account = await build(dashboard).create_account(spec(), idempotency_key="k1")

    assert account.state is AccountState.ACTIVE
    assert dashboard.jobs("gv14050042") == {"total_data": "30.000", "date": "2026-12-01 00:00:00"}
    assert account.usage.quota.total_bytes == 30 * GIB
    assert account.expires_at == EXPIRY
    assert set(dashboard.keys) == {"secret-key"}


@pytest.mark.asyncio
async def test_the_customer_is_handed_the_share_link() -> None:
    dashboard = Dashboard()

    account = await build(dashboard).create_account(spec(), idempotency_key="k1")

    assert account.subscription_url == "https://wg.test/#/share?ShareID=share-pub0="


@pytest.mark.asyncio
async def test_creating_twice_does_not_add_a_second_peer() -> None:
    dashboard = Dashboard()
    adapter = build(dashboard)

    await adapter.create_account(spec(), idempotency_key="k1")
    await adapter.create_account(spec(), idempotency_key="k1")

    assert len(dashboard.peers) == 1
    # And the retry replaced the limits rather than stacking a second set.
    assert len(next(iter(dashboard.peers.values()))["jobs"]) == 2


@pytest.mark.asyncio
async def test_an_unlimited_plan_gets_no_traffic_job() -> None:
    dashboard = Dashboard()

    await build(dashboard).create_account(spec(quota=TrafficQuota(None)), idempotency_key="k1")

    assert "total_data" not in dashboard.jobs("gv14050042")


@pytest.mark.asyncio
async def test_suspend_restricts_and_resume_allows_the_same_peer() -> None:
    dashboard = Dashboard()
    adapter = build(dashboard)
    await adapter.create_account(spec(), idempotency_key="k1")
    ref = adapter.ref("gv14050042")

    suspended = await adapter.suspend(ref, idempotency_key="k2")
    resumed = await adapter.resume(ref, idempotency_key="k3")

    assert suspended.state is AccountState.SUSPENDED
    assert resumed.state is AccountState.ACTIVE
    assert len(dashboard.peers) == 1


@pytest.mark.asyncio
async def test_renewing_moves_the_date_job_instead_of_adding_one() -> None:
    dashboard = Dashboard()
    adapter = build(dashboard)
    await adapter.create_account(spec(), idempotency_key="k1")

    renewed = await adapter.renew(
        adapter.ref("gv14050042"), extend_by=timedelta(days=30), idempotency_key="k2"
    )

    assert dashboard.jobs("gv14050042")["date"] == "2026-12-31 00:00:00"
    assert renewed.expires_at == EXPIRY + timedelta(days=30)


@pytest.mark.asyncio
async def test_renewing_a_restricted_peer_lets_it_connect_again() -> None:
    dashboard = Dashboard()
    adapter = build(dashboard)
    await adapter.create_account(spec(), idempotency_key="k1")
    dashboard.restricted.update(dashboard.peers)

    renewed = await adapter.renew(
        adapter.ref("gv14050042"), extend_by=timedelta(days=30), idempotency_key="k2"
    )

    assert renewed.state is AccountState.ACTIVE


@pytest.mark.asyncio
async def test_usage_is_received_plus_sent_in_bytes() -> None:
    dashboard = Dashboard()
    adapter = build(dashboard)
    await adapter.create_account(spec(), idempotency_key="k1")
    peer = next(iter(dashboard.peers.values()))
    peer["total_receive"], peer["total_sent"] = 1.5, 0.5

    usage = await adapter.usage(adapter.ref("gv14050042"))

    assert usage.used_bytes == 2 * GIB


@pytest.mark.asyncio
async def test_a_pasted_share_link_finds_its_peer() -> None:
    dashboard = Dashboard()
    adapter = build(dashboard)
    created = await adapter.create_account(spec(), idempotency_key="k1")

    found = await adapter.find_by_subscription(created.subscription_url)

    assert found is not None and found.ref.username == "gv14050042"


@pytest.mark.asyncio
async def test_delete_removes_the_peer_and_a_second_delete_is_quiet() -> None:
    dashboard = Dashboard()
    adapter = build(dashboard)
    await adapter.create_account(spec(), idempotency_key="k1")
    ref = adapter.ref("gv14050042")

    await adapter.delete_account(ref, idempotency_key="k2")
    await adapter.delete_account(ref, idempotency_key="k3")

    assert dashboard.peers == {}
    with pytest.raises(AccountNotFound):
        await adapter.get_account(ref)
