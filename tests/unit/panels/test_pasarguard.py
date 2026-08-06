"""PasarGuard adapter behaviour.

PasarGuard is the panel the platform runs in production today, so this is the
most detailed adapter suite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from geekvpn.domain.panels.enums import AccountState, PanelKind
from geekvpn.domain.panels.errors import AccountAlreadyExists
from geekvpn.domain.panels.values import AccountSpec, TrafficQuota
from geekvpn.infrastructure.panels.adapters.pasarguard import PasarGuardAdapter
from geekvpn.infrastructure.panels.factory import PanelFactory
from tests.panel_fakes import PANEL_ID, FakePanelServer

EXPIRY = datetime(2026, 12, 1, tzinfo=UTC)
GIB = 1024**3


def user_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "username": "cust-1",
        "status": "active",
        "used_traffic": 5 * GIB,
        "data_limit": 30 * GIB,
        "expire": int(EXPIRY.timestamp()),
        "subscription_url": "https://panel.test/sub/abc",
        "links": ["vless://one", "vless://two"],
    }
    payload.update(overrides)
    return payload


def build(server: FakePanelServer) -> PasarGuardAdapter:
    adapter = PanelFactory().build(
        PanelKind.PASARGUARD,
        {
            "base_url": "https://panel.test",
            "username": "admin",
            "password": "secret",
            "max_attempts": 1,
        },
        panel_id=PANEL_ID,
        transport=server.transport,
    )
    return adapter  # type: ignore[return-value]


def with_auth(server: FakePanelServer) -> FakePanelServer:
    return server.route(
        "POST", "/api/admin/token", json={"access_token": "t", "token_type": "bearer"}
    )


SPEC = AccountSpec(username="cust-1", quota=TrafficQuota.from_gib(30), expires_at=EXPIRY)


@pytest.mark.asyncio
async def test_create_sends_bytes_and_an_epoch_expiry() -> None:
    """Unit conversion at the boundary is the whole job of an adapter."""
    captured: dict[str, object] = {}

    def create(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.read()))
        return httpx.Response(200, json=user_payload())

    server = with_auth(FakePanelServer()).route("POST", "/api/user", handler=create)
    account = await build(server).create_account(SPEC, idempotency_key="k1")

    assert captured["data_limit"] == 30 * GIB
    assert captured["expire"] == int(EXPIRY.timestamp())
    # Never reset a paid customer's traffic on a schedule by accident.
    assert captured["data_limit_reset_strategy"] == "no_reset"
    assert account.state is AccountState.ACTIVE
    assert account.usage.used_bytes == 5 * GIB


@pytest.mark.asyncio
async def test_the_bearer_token_is_fetched_once_and_reused() -> None:
    """Logging in per request triples latency and can trip panel rate limits."""
    server = with_auth(FakePanelServer())
    server.prefix("GET", "/api/user/", json=user_payload())
    adapter = build(server)

    await adapter.get_account(adapter.ref("cust-1"))
    await adapter.get_account(adapter.ref("cust-1"))

    assert server.count("POST", "/api/admin/token") == 1


@pytest.mark.asyncio
async def test_a_lost_create_response_is_recovered_rather_than_failed() -> None:
    """The panel created the user, the response never arrived, we retried.

    Failing here would strand a customer who has already paid, so a 409 whose
    existing account matches what we asked for is treated as success.
    """
    server = with_auth(FakePanelServer())
    server.route("POST", "/api/user", status=409, json={"detail": "exists"})
    server.prefix("GET", "/api/user/", json=user_payload())

    account = await build(server).create_account(SPEC, idempotency_key="k1")

    assert account.ref.username == "cust-1"


@pytest.mark.asyncio
async def test_a_genuine_username_collision_still_raises() -> None:
    """Same name, different quota means it is somebody else's account."""
    server = with_auth(FakePanelServer())
    server.route("POST", "/api/user", status=409, json={"detail": "exists"})
    server.prefix("GET", "/api/user/", json=user_payload(data_limit=99 * GIB))

    with pytest.raises(AccountAlreadyExists):
        await build(server).create_account(SPEC, idempotency_key="k1")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("active", AccountState.ACTIVE),
        ("on_hold", AccountState.ACTIVE),
        ("disabled", AccountState.SUSPENDED),
        ("expired", AccountState.EXPIRED),
        ("limited", AccountState.QUOTA_EXHAUSTED),
    ],
)
@pytest.mark.asyncio
async def test_panel_statuses_map_onto_the_domain_vocabulary(
    status: str, expected: AccountState
) -> None:
    server = with_auth(FakePanelServer())
    server.prefix("GET", "/api/user/", json=user_payload(status=status))
    adapter = build(server)

    account = await adapter.get_account(adapter.ref("cust-1"))

    assert account.state is expected


@pytest.mark.asyncio
async def test_renewing_an_expired_account_grants_the_full_paid_period() -> None:
    """Extending from a past expiry would silently shorten what was bought.

    A customer who renews three days late must still receive 30 full days.
    """
    import json

    captured: dict[str, object] = {}
    past = datetime(2020, 1, 1, tzinfo=UTC)

    def modify(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.read()))
        return httpx.Response(200, json=user_payload())

    server = with_auth(FakePanelServer())
    server.prefix("GET", "/api/user/", json=user_payload(expire=int(past.timestamp())))
    server.prefix("PUT", "/api/user/", handler=modify)
    adapter = build(server)

    await adapter.renew(adapter.ref("cust-1"), extend_by=timedelta(days=30), idempotency_key="k1")

    granted = datetime.fromtimestamp(int(captured["expire"]), tz=UTC)
    assert granted > datetime.now(UTC) + timedelta(days=29)


@pytest.mark.asyncio
async def test_bulk_usage_returns_only_the_requested_accounts() -> None:
    server = with_auth(FakePanelServer())
    server.route(
        "GET",
        "/api/users",
        json={
            "users": [
                user_payload(username="cust-1"),
                user_payload(username="cust-2", used_traffic=1 * GIB),
                user_payload(username="someone-else"),
            ]
        },
    )
    adapter = build(server)

    usage = await adapter.bulk_usage([adapter.ref("cust-1"), adapter.ref("cust-2")])

    assert set(usage) == {"cust-1", "cust-2"}
    assert usage["cust-2"].used_bytes == 1 * GIB


@pytest.mark.asyncio
async def test_usage_reports_remaining_traffic() -> None:
    server = with_auth(FakePanelServer())
    server.prefix("GET", "/api/user/", json=user_payload())
    adapter = build(server)

    usage = await adapter.usage(adapter.ref("cust-1"))

    assert usage.remaining_bytes == 25 * GIB
    assert usage.fraction_used == pytest.approx(5 / 30)
