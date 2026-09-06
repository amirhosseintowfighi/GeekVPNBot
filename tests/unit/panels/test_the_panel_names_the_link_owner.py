"""Asking the panel who a pasted subscription link belongs to.

Four rounds went the other way - read every account, hunt for the link under
whichever key this fork spells it, fall back to the id inside the token, then
prove that id is not a different customer on a different server - and a real
link still came back "not found". Every one of those rounds was us guessing at
an answer the panel will simply tell us: `<sub path>/info` names the account.

The host in the pasted link is deliberately not used. It may be a second domain
or a reverse proxy, and it may be a server that is not ours at all - a paste box
that fetches whatever host it is handed is an outbound request tool.
"""

from __future__ import annotations

import httpx
import pytest

from tests.panel_fakes import FakePanelServer
from tests.unit.panels.test_pasarguard import build, user_payload, with_auth

pytestmark = pytest.mark.unit

TOKEN = "djMsMSwxNzg4NDQxMjYw.Xs1JrAv7"
LINK = f"https://sub.other-domain.example/sub/{TOKEN}"


def _server(*, info: dict[str, object] | None, users: list[dict[str, object]] | None = None):
    server = with_auth(FakePanelServer())
    server.route(
        "GET",
        f"/sub/{TOKEN}/info",
        json=info if info is not None else {"detail": "Not Found"},
        status=200 if info is not None else 404,
    )
    server.route("GET", "/api/users", json={"users": users or []})
    server.prefix("GET", "/api/user/", json=user_payload(username="cust-1"))
    return server


@pytest.mark.asyncio
async def test_the_account_the_panel_names_is_the_one_returned():
    adapter = build(_server(info={"username": "cust-1"}))

    found = await adapter.find_by_subscription(LINK)

    assert found is not None
    assert found.ref.username == "cust-1"


@pytest.mark.asyncio
async def test_the_account_list_is_never_read_when_the_panel_answers():
    """The list scan is the part that kept being wrong. It must not be what
    decides the answer when the panel has already given one."""
    server = _server(info={"username": "cust-1"})
    adapter = build(server)

    await adapter.find_by_subscription(LINK)

    assert not [c for c in server.calls if c.url.path == "/api/users"]


@pytest.mark.asyncio
async def test_only_the_path_travels_and_the_host_is_ours():
    """The pasted host is never contacted."""
    server = _server(info={"username": "cust-1"})
    adapter = build(server)

    await adapter.find_by_subscription(LINK)

    assert {c.url.host for c in server.calls} == {"panel.test"}


@pytest.mark.asyncio
async def test_a_token_this_panel_did_not_mint_is_not_a_failure():
    """404 means "not mine", which is an answer. Raising here would turn one
    stray paste into "every panel is down"."""
    adapter = build(_server(info=None))

    assert await adapter.find_by_subscription(LINK) is None


@pytest.mark.asyncio
async def test_a_refusal_still_lets_the_list_scan_find_it():
    """Panels that serve no `/info` must keep working the old way."""
    rows = [user_payload(username="gv1", subscription_url=f"/sub/{TOKEN}")]
    adapter = build(_server(info=None, users=rows))

    found = await adapter.find_by_subscription(LINK)

    assert found is not None
    assert found.ref.username == "gv1"


@pytest.mark.asyncio
async def test_an_html_error_page_is_read_as_no_answer():
    """Some deployments serve the front-end for unknown paths, with a 200."""
    server = with_auth(FakePanelServer())
    server.route(
        "GET",
        f"/sub/{TOKEN}/info",
        handler=lambda _r: httpx.Response(200, text="<!doctype html>"),
    )
    server.route("GET", "/api/users", json={"users": []})

    assert await build(server).find_by_subscription(LINK) is None
