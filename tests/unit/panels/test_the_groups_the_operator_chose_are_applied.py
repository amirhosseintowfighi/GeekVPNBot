"""An account created in no group has no access.

The operator picks groups on the servers screen, the choice is stored, and the
bot creates accounts that arrive on the panel with the Groups column empty - so
the customer is handed a subscription link that resolves to nothing. Everything
in between returns 200.

Two things were wrong and they hide each other. The id made the trip through
JSON and an HTML form, so it arrived as `"1"` where the panel keys groups by
integer; and nothing ever looked at what came back, so an ignored `group_ids`
was indistinguishable from a working create.
"""

from __future__ import annotations

import httpx
import pytest
from structlog.testing import capture_logs

from geekvpn.domain.panels.enums import PanelKind
from geekvpn.domain.panels.values import AccountSpec, TrafficQuota
from tests.panel_fakes import PANEL_ID, FakePanelServer
from tests.unit.panels.test_pasarguard import EXPIRY, user_payload, with_auth

pytestmark = pytest.mark.unit

SPEC = AccountSpec(username="gv1", quota=TrafficQuota.from_gib(20), expires_at=EXPIRY)


def _events(logs: list[dict]) -> list[str]:
    """Only the ones this module emits; the HTTP client is chatty."""
    wanted = {"panel.groups_not_applied", "panel.account_created_without_groups"}
    return [entry["event"] for entry in logs if entry.get("event") in wanted]


def _adapter(*, default_groups=(), created=None):
    from geekvpn.infrastructure.panels.factory import PanelFactory

    server = with_auth(FakePanelServer())
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        sent.append(json.loads(request.content))
        return httpx.Response(200, json=created if created is not None else user_payload())

    server.route("POST", "/api/user", handler=handler)
    adapter = PanelFactory().build(
        PanelKind.PASARGUARD,
        {
            "base_url": "https://panel.test",
            "username": "admin",
            "password": "secret",
            "max_attempts": 1,
            "default_groups": default_groups,
        },
        panel_id=PANEL_ID,
        transport=server.transport,
    )
    return adapter, sent


@pytest.mark.asyncio
async def test_a_numeric_group_id_is_sent_as_a_number():
    """The bug. The operator's choice arrives as a string because it travelled
    through JSON and a form; the panel keys groups by integer, and `["1"]` is
    either rejected outright or accepted and matched against nothing."""
    adapter, sent = _adapter(default_groups=("1", "2"))

    await adapter.create_account(SPEC, idempotency_key="k")

    assert sent[0]["group_ids"] == [1, 2]


@pytest.mark.asyncio
async def test_a_group_id_that_is_not_a_number_is_left_alone():
    """Not every fork keys groups by integer, and coercing a name to nothing
    would trade one silent failure for another."""
    adapter, sent = _adapter(default_groups=("premium",))

    await adapter.create_account(SPEC, idempotency_key="k")

    assert sent[0]["group_ids"] == ["premium"]


@pytest.mark.asyncio
async def test_a_node_with_no_groups_sends_no_group_field():
    """An absent key lets the panel apply its own default. An empty list is a
    different instruction - it says "no groups" - and the two must not be
    confused."""
    adapter, sent = _adapter()

    await adapter.create_account(SPEC, idempotency_key="k")

    assert "group_ids" not in sent[0]


@pytest.mark.asyncio
async def test_the_spec_wins_over_the_nodes_default():
    adapter, sent = _adapter(default_groups=("1",))

    await adapter.create_account(
        AccountSpec(
            username="gv1",
            quota=TrafficQuota.from_gib(20),
            expires_at=EXPIRY,
            group_tags=("7",),
        ),
        idempotency_key="k",
    )

    assert sent[0]["group_ids"] == [7]


# -- saying so ------------------------------------------------------------
#
# `structlog.testing.capture_logs` rather than `caplog`: these loggers are
# structlog's, and the events never reach the stdlib handler caplog installs.


@pytest.mark.asyncio
async def test_a_create_that_lands_in_no_group_is_reported():
    """The account exists and the customer has paid, so this cannot raise -
    but it must not be silent either. Until now the create returned 200, the
    order completed, and the first anybody heard was a customer saying their
    config does not work."""
    adapter, _ = _adapter(default_groups=("1",), created=user_payload(group_ids=[]))

    with capture_logs() as logs:
        await adapter.create_account(SPEC, idempotency_key="k")

    assert _events(logs) == ["panel.groups_not_applied"]


@pytest.mark.asyncio
async def test_a_node_with_no_groups_configured_is_reported_too():
    """On this panel "no groups" is not a neutral default - it is an account
    with no access - so an unconfigured node is worth a line of its own."""
    adapter, _ = _adapter()

    with capture_logs() as logs:
        await adapter.create_account(SPEC, idempotency_key="k")

    assert _events(logs) == ["panel.account_created_without_groups"]


@pytest.mark.asyncio
async def test_a_create_that_worked_says_nothing():
    adapter, _ = _adapter(default_groups=("1",), created=user_payload(group_ids=[1]))

    with capture_logs() as logs:
        await adapter.create_account(SPEC, idempotency_key="k")

    assert _events(logs) == []


@pytest.mark.asyncio
async def test_a_panel_that_does_not_echo_the_groups_is_not_accused():
    """Some builds answer a create without repeating what they applied.
    Complaining there would train the operator to ignore the warning."""
    adapter, _ = _adapter(default_groups=("1",), created=user_payload())

    with capture_logs() as logs:
        await adapter.create_account(SPEC, idempotency_key="k")

    assert _events(logs) == []
