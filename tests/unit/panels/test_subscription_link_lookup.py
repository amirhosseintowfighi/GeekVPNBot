"""Matching a pasted subscription link to an account on a panel.

The hostname in the link cannot be compared. The panel reports whatever base URL
it was configured with, the customer holds whatever they were sent, and behind a
reverse proxy or a second domain those differ - so a strict comparison would
refuse every real link on exactly the setups people actually run.
"""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.panels.adapters._common import sub_token

pytestmark = pytest.mark.unit


def test_the_same_account_behind_two_hostnames_matches():
    """The reason this compares tokens at all."""
    ours = "https://panel.internal:8000/sub/AbC123"
    theirs = "https://vpn.example.com/sub/AbC123"

    assert sub_token(ours) == sub_token(theirs)


def test_a_trailing_slash_is_not_a_different_account():
    assert sub_token("https://x/sub/tok/") == sub_token("https://x/sub/tok")


def test_a_query_string_is_not_part_of_the_identity():
    """Clients append their own format hints to these links."""
    assert sub_token("https://x/sub/tok?format=v2ray") == "tok"


def test_surrounding_whitespace_from_a_paste_is_ignored():
    assert sub_token("  https://x/sub/tok  ") == "tok"


def test_two_different_accounts_do_not_collide():
    assert sub_token("https://x/sub/aaa") != sub_token("https://x/sub/bbb")


def test_nothing_in_means_nothing_out():
    """An empty token must never match; it would match every blank
    `subscription_url` on the panel and hand over an arbitrary account."""
    assert sub_token("") == ""
    assert sub_token("   ") == ""


def test_a_bare_username_is_its_own_token():
    """Some panels are configured with no path at all, and some customers paste
    the username rather than the link."""
    assert sub_token("ali") == "ali"


def test_an_unreadable_account_list_is_not_the_same_as_no_match():
    """A reply we cannot parse used to return `None`, which the claim reported
    to the customer as "no such subscription" - for a link that was real, on a
    panel whose response shape we had guessed wrong. It points them at the one
    thing that is not the problem."""
    import asyncio
    from unittest.mock import AsyncMock, Mock

    from geekvpn.domain.panels.errors import PanelContractViolation
    from geekvpn.infrastructure.panels.adapters.pasarguard import PasarGuardAdapter

    adapter = Mock(spec=PasarGuardAdapter)
    adapter._http = Mock()
    adapter._http.request = AsyncMock(return_value=Mock())
    # An envelope we did not expect: neither a list nor a dict holding one.
    adapter._http.json = Mock(return_value={"data": {"page": 1}})
    adapter._auth_headers = AsyncMock(return_value={})
    adapter.kind = Mock(value="pasarguard")

    with pytest.raises(PanelContractViolation):
        asyncio.run(
            PasarGuardAdapter.find_by_subscription(adapter, "https://x/sub/token")
        )
