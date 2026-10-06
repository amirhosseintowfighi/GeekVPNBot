"""Sanaei and Alireza accounts arrive with their subscription link.

The adapter set `subId` on every client and never said where it could be
fetched, so an x-ui customer was delivered an account with no link at all.
"""

from __future__ import annotations

import pytest

from geekvpn.domain.panels.enums import PanelKind
from tests.panel_fakes import FakePanelServer
from tests.unit.panels import test_xui_family as xui

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("kind", "prefix"), xui.FAMILY)
async def test_the_link_is_the_subscription_server_plus_the_sub_id(
    kind: PanelKind, prefix: str
) -> None:
    server = xui.with_auth(FakePanelServer())
    server.prefix("GET", f"{prefix}/get", json=xui.inbound(xui.client(subId="abc123")))
    server.prefix("GET", f"{prefix}/getClientTraffics", json=xui.traffic())
    adapter = xui.build(kind, server, subscriptionUrl="https://sub.example.com:2096/sub/")

    account = await adapter.get_account(adapter.ref("cust-1"))

    assert account.subscription_url == "https://sub.example.com:2096/sub/abc123"


@pytest.mark.parametrize(("kind", "prefix"), xui.FAMILY)
async def test_without_a_subscription_server_there_is_no_link(
    kind: PanelKind, prefix: str
) -> None:
    server = xui.with_auth(FakePanelServer())
    server.prefix("GET", f"{prefix}/get", json=xui.inbound(xui.client(subId="abc123")))
    server.prefix("GET", f"{prefix}/getClientTraffics", json=xui.traffic())
    adapter = xui.build(kind, server)

    account = await adapter.get_account(adapter.ref("cust-1"))

    assert account.subscription_url is None
