"""A leaked link replaced by a new one, on every panel that can do it.

The button existed in the bot and the Mini App for months and always failed:
no adapter could reissue credentials. These pin what each panel is asked.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from geekvpn.application.provisioning.subscription_admin import SubscriptionAdminService
from geekvpn.domain.panels.enums import AccountState, Capability, PanelKind
from geekvpn.domain.panels.values import AccountUsage, PanelAccount, PanelAccountRef
from geekvpn.domain.provisioning import Subscription
from geekvpn.domain.provisioning.errors import RotationUnavailable
from geekvpn.infrastructure.panels.registry import load_bundled_adapters, registry
from tests.panel_fakes import FakePanelServer
from tests.unit.panels import test_marzban as marzban
from tests.unit.panels import test_xui_family as xui
from tests.unit.provisioning.fakes import (
    FakePanel,
    FakePanelProvider,
    FrozenClock,
    InMemoryNodes,
    InMemorySubscriptions,
    node,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 27, tzinfo=UTC)


async def test_marzban_is_asked_to_revoke_the_subscription() -> None:
    path = "/api/user/cust-1/revoke_sub"
    calls: list[str] = []

    def revoke(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=marzban.user_payload(subscription_url="/sub/new"))

    server = marzban.with_auth(FakePanelServer())
    server.route("POST", path, handler=revoke)
    server.route("GET", "/api/user/cust-1", json=marzban.user_payload(subscription_url="/sub/new"))
    adapter = marzban.build(server)

    account = await adapter.revoke_access(adapter.ref("cust-1"), idempotency_key="k")

    assert calls == [path]
    assert account.subscription_url is not None
    assert account.subscription_url.endswith("/sub/new")


@pytest.mark.parametrize(("kind", "prefix"), xui.FAMILY)
async def test_xui_gets_a_new_client_id_and_sub_id_addressed_by_the_old_one(
    kind: PanelKind, prefix: str
) -> None:
    captured: dict[str, object] = {}

    def update(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured.update(json.loads(request.read()))
        return httpx.Response(200, json={"success": True, "obj": None})

    old = xui.client(subId="oldsub", totalGB=77 * xui.GIB)
    server = xui.with_auth(FakePanelServer())
    server.prefix("GET", f"{prefix}/get", json=xui.inbound(old))
    server.prefix("GET", f"{prefix}/getClientTraffics", json=xui.traffic())
    server.prefix("POST", f"{prefix}/updateClient", handler=update)
    adapter = xui.build(kind, server)

    await adapter.revoke_access(adapter.ref("cust-1"), idempotency_key="k")

    sent = json.loads(str(captured["settings"]))["clients"][0]
    assert str(captured["path"]).endswith(f"/updateClient/{old['id']}")
    assert sent["id"] != old["id"]
    assert sent["subId"] != "oldsub"
    # Everything that was sold stays exactly as it was.
    assert sent["totalGB"] == 77 * xui.GIB
    assert sent["email"] == "cust-1"


@pytest.mark.parametrize(
    "kind",
    [PanelKind.MARZBAN, PanelKind.MARZNESHIN, PanelKind.PASARGUARD, PanelKind.SANAEI, PanelKind.ALIREZA],
)
def test_every_bundled_panel_declares_it(kind: PanelKind) -> None:
    load_bundled_adapters()
    assert Capability.REVOKE_ACCESS in registry.get(kind).capabilities


# -- the service around it -----------------------------------------------------


class RotatingPanel(FakePanel):
    capabilities = frozenset({Capability.REVOKE_ACCESS})

    async def revoke_access(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        return PanelAccount(
            ref=PanelAccountRef(panel_id=ref.panel_id, username=ref.username, external_id="new-id"),
            state=AccountState.ACTIVE,
            usage=AccountUsage(used_bytes=0, measured_at=NOW),
            # The panel answers on its own API host, as a split setup does.
            subscription_url="https://api.panel.example:8443/sub/new-token",
        )


async def rotate(panel: FakePanel) -> Subscription:
    sub = Subscription.activate(
        "sub-1",
        user_id=1,
        order_id="o",
        plan_id="p",
        remote_username="cust-1",
        now=NOW,
        duration_days=30,
        node_id="node-de",
        subscription_url="https://shop.example/sub/old-token",
    )
    subs = InMemorySubscriptions()
    await subs.add(sub)
    service = SubscriptionAdminService(
        subscriptions=subs,
        nodes=InMemoryNodes(node("node-de")),
        panels=FakePanelProvider(panel),
        clock=FrozenClock(NOW),
        shop_hosts={"node-de": "https://shop.example"},
    )
    return await service.rotate_access("sub-1")


async def test_the_new_link_is_stored_on_the_shops_own_host() -> None:
    rotated = await rotate(RotatingPanel())

    assert rotated.subscription_url == "https://shop.example/sub/new-token"
    assert rotated.remote_id == "new-id"


async def test_a_panel_that_cannot_reissue_is_refused_not_faked() -> None:
    """Returning the old link as if it were new would leave a leaked link working."""
    with pytest.raises(RotationUnavailable):
        await rotate(FakePanel())
