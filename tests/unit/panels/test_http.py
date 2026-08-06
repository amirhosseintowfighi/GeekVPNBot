"""The shared HTTP client.

This class is the single place where "the network is unreliable" is handled.
If it is wrong, every adapter is wrong, so it is tested directly rather than
only through adapters.
"""

from __future__ import annotations

import httpx
import pytest

from geekvpn.domain.panels.errors import (
    PanelAuthFailed,
    PanelContractViolation,
    PanelRateLimited,
    PanelUnreachable,
)
from geekvpn.infrastructure.panels.http import PanelHttpClient
from tests.panel_fakes import FakePanelServer


def client(server: FakePanelServer, **kw: object) -> PanelHttpClient:
    defaults: dict[str, object] = {
        "base_url": "https://panel.test",
        "panel_name": "test",
        "max_attempts": 3,
        "transport": server.transport,
    }
    defaults.update(kw)
    return PanelHttpClient(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_a_transient_server_error_is_retried_and_then_succeeds() -> None:
    """Panels restart. A 503 mid-deploy must not fail a customer's purchase."""
    attempts = {"n": 0}

    def flaky(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503, json={"detail": "restarting"})
        return httpx.Response(200, json={"ok": True})

    server = FakePanelServer().prefix("GET", "/", handler=flaky)
    http = client(server)

    response = await http.request("GET", "/thing")

    assert response.status_code == 200
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_retries_are_bounded_and_then_give_up() -> None:
    """Unbounded retries turn one sick panel into a platform-wide stall."""
    server = FakePanelServer().prefix("GET", "/", status=503, json={"d": 1})
    http = client(server, max_attempts=3)

    with pytest.raises(PanelUnreachable):
        await http.request("GET", "/thing")

    assert len(server.calls) == 3


@pytest.mark.asyncio
async def test_client_errors_are_not_retried() -> None:
    """A 400 will be a 400 forever. Retrying only wastes the panel's capacity."""
    server = FakePanelServer().prefix("GET", "/", status=400, json={"detail": "nope"})
    http = client(server)

    with pytest.raises(PanelContractViolation):
        await http.request("GET", "/thing")

    assert len(server.calls) == 1


@pytest.mark.asyncio
async def test_401_becomes_a_terminal_auth_failure() -> None:
    server = FakePanelServer().prefix("GET", "/", status=401, json={"detail": "no"})

    with pytest.raises(PanelAuthFailed) as excinfo:
        await client(server).request("GET", "/thing")

    assert excinfo.value.retryable is False
    assert len(server.calls) == 1


@pytest.mark.asyncio
async def test_429_carries_retry_after_so_the_scheduler_can_back_off() -> None:
    server = FakePanelServer().prefix(
        "GET",
        "/",
        handler=lambda _r: httpx.Response(
            429, json={"detail": "slow down"}, headers={"Retry-After": "42"}
        ),
    )
    http = client(server, max_attempts=1)

    with pytest.raises(PanelRateLimited) as excinfo:
        await http.request("GET", "/thing")

    assert excinfo.value.retry_after_seconds == 42
    assert excinfo.value.retryable is True


@pytest.mark.asyncio
async def test_a_timeout_is_reported_as_unreachable() -> None:
    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("too slow")

    server = FakePanelServer().prefix("GET", "/", handler=timeout)

    with pytest.raises(PanelUnreachable) as excinfo:
        await client(server, max_attempts=1).request("GET", "/thing")

    assert excinfo.value.retryable is True


@pytest.mark.asyncio
async def test_unparseable_json_is_a_contract_violation() -> None:
    """An HTML error page from a reverse proxy must not read as a bad request."""
    server = FakePanelServer().prefix(
        "GET", "/", handler=lambda _r: httpx.Response(200, text="<html>502</html>")
    )
    http = client(server)
    response = await http.request("GET", "/thing")

    with pytest.raises(PanelContractViolation):
        http.json(response)


@pytest.mark.asyncio
async def test_allow_status_lets_the_adapter_handle_404_itself() -> None:
    server = FakePanelServer().prefix("GET", "/", status=404, json={"detail": "gone"})
    http = client(server)

    response = await http.request("GET", "/thing", allow_status=(404,))

    assert response.status_code == 404
