"""Finding an account whose panel does not put the link in the account list.

Three of this operator's panels answered `/api/users` with accounts that carry
no subscription link under any name - so there was nothing to compare a pasted
link against, and every real claim was refused.

The link itself carries the answer: these panels build the token as base64 of
`v3,<account id>,<created>`. So the id is matched instead.

The security property is the one to keep. An account id is only unique *within*
a panel, so a token minted by one server matches a different customer's account
on another. The match is therefore confirmed against the account itself before
anything is attached - handing somebody a stranger's service is far worse than
refusing a genuine claim, and this is a bearer link anybody who has seen it once
could paste.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from geekvpn.domain.panels.enums import AccountState
from geekvpn.domain.panels.errors import PanelContractViolation
from geekvpn.domain.panels.values import (
    AccountUsage,
    PanelAccount,
    PanelAccountRef,
    TrafficQuota,
)
from geekvpn.infrastructure.panels.adapters.pasarguard import PasarGuardAdapter

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 4, tzinfo=UTC)

TOKEN = "djMsMSwxNzg4NDQxMjYw.Xs1JrAv7_-7Tia_5mhOQv4qI70A4ASA69x8LCWL2Mvw"
LINK = f"https://panel.doping.games:8443/sub/{TOKEN}"

#: What the panels in question actually return: no link anywhere on the row.
LINKLESS = [{"id": 1, "username": "gv1"}, {"id": 2, "username": "gv2"}]


def _adapter(rows: list[dict[str, Any]], *, confirms: str | None) -> Any:
    adapter = Mock(spec=PasarGuardAdapter)
    adapter._http = Mock()
    adapter._http.request = AsyncMock(return_value=Mock())
    adapter._http.json = Mock(return_value={"users": rows})
    adapter._auth_headers = AsyncMock(return_value={})
    adapter.kind = Mock(value="pasarguard")
    adapter._panel_id = __import__("uuid").uuid4()
    # The real mapper, so a row matched by link returns an account rather than
    # a Mock that would agree with any assertion put to it.
    adapter._to_account = lambda item: PanelAccount(
        ref=PanelAccountRef(
            panel_id=adapter._panel_id, username=str(item["username"])
        ),
        state=AccountState.ACTIVE,
        usage=AccountUsage(used_bytes=0, measured_at=NOW, quota=TrafficQuota()),
        subscription_url=item.get("subscription_url"),
    )

    async def get_account(ref: PanelAccountRef) -> PanelAccount:
        return PanelAccount(
            ref=ref,
            state=AccountState.ACTIVE,
            usage=AccountUsage(
                used_bytes=0, measured_at=NOW, quota=TrafficQuota()
            ),
            subscription_url=confirms,
        )

    adapter.get_account = get_account
    return adapter


def _find(adapter: Any, url: str = LINK) -> Any:
    return asyncio.run(PasarGuardAdapter.find_by_subscription(adapter, url))


def test_the_account_is_found_by_the_id_inside_the_link():
    """The reported failure, with the panel's real answer shape."""
    adapter = _adapter(LINKLESS, confirms=f"/sub/{TOKEN}")

    found = _find(adapter)

    assert found is not None
    assert found.ref.username == "gv1"


def test_an_id_match_the_account_does_not_confirm_is_refused():
    """The security property. An id is unique only within a panel, so a token
    from one server matches a stranger's account on another - and this is a
    bearer link anybody who has seen it could paste."""
    adapter = _adapter(LINKLESS, confirms="/sub/some-completely-different-token")

    assert _find(adapter) is None


def test_an_account_that_cannot_confirm_at_all_is_refused():
    """No link on the single-account endpoint either. Unverifiable, so not
    attached: refusing a genuine claim is the cheaper mistake."""
    adapter = _adapter(LINKLESS, confirms=None)

    assert _find(adapter) is None


def test_a_link_in_the_list_still_wins_without_a_second_call():
    """When the panel does carry it, the link is proof by itself."""
    rows = [{"id": 9, "username": "gv9", "subscription_url": f"/sub/{TOKEN}"}]
    adapter = _adapter(rows, confirms=None)

    found = _find(adapter)

    assert found is not None
    assert found.ref.username == "gv9"


def test_an_id_nobody_has_is_simply_not_found():
    """The account is not on this panel. No error - the caller asks the next
    one, and only the last silence means anything."""
    adapter = _adapter([{"id": 7, "username": "gv7"}], confirms=None)

    assert _find(adapter) is None


def test_a_token_we_cannot_read_and_no_links_is_still_a_contract_violation():
    """Neither avenue available: we cannot match by link because there are
    none, and cannot match by id because this token is not that shape. Saying
    "no such subscription" would be a guess dressed as an answer."""
    adapter = _adapter(LINKLESS, confirms=None)

    with pytest.raises(PanelContractViolation):
        _find(adapter, "https://x/sub/an-entirely-different-token-shape")
