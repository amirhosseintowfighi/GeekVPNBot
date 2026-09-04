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


def test_the_link_that_was_reported_as_missing():
    """A real one, with a port and a dot inside the token."""
    pasted = (
        "https://panel.doping.games:8443/sub/"
        "djMsMSwxNzg4NDQxMjYw.Xs1JrAv7_-7Tia_5mhOQv4qI70A4ASA69x8LCWL2Mvw"
    )

    # The same account as the panel would report it: relative path, no host.
    reported = "/sub/djMsMSwxNzg4NDQxMjYw.Xs1JrAv7_-7Tia_5mhOQv4qI70A4ASA69x8LCWL2Mvw"

    assert sub_token(pasted) == sub_token(reported)


def test_a_link_under_another_field_name_is_still_found():
    """These forks rename things between versions, and a lookup that knows one
    spelling reports every real link as missing."""
    from geekvpn.infrastructure.panels.adapters._common import subscription_of

    for key in ("subscription_url", "subscription_link", "sub_url", "subscriptionUrl"):
        assert subscription_of({key: "/sub/abc"}) == "/sub/abc"


def test_an_empty_link_is_not_a_link():
    from geekvpn.infrastructure.panels.adapters._common import subscription_of

    assert subscription_of({"subscription_url": "   "}) == ""
    assert subscription_of({"username": "ali"}) == ""


def test_accounts_with_no_link_at_all_is_a_contract_violation():
    """Not "no match". If the panel returned accounts and none carried a link
    under any name we know, we are reading the wrong field - and "no such
    subscription" sends the customer to check the one thing that is fine."""
    from geekvpn.domain.panels.errors import PanelContractViolation
    from geekvpn.infrastructure.panels.adapters._common import require_a_readable_link

    with pytest.raises(PanelContractViolation):
        require_a_readable_link(seen=40, with_link=0, panel="pasarguard")


def test_a_genuinely_absent_account_is_still_just_absent():
    """The panel had accounts, they had links, ours was not among them. That
    is the one case where "not found" is the honest answer."""
    from geekvpn.infrastructure.panels.adapters._common import require_a_readable_link

    require_a_readable_link(seen=40, with_link=40, panel="pasarguard")


def test_an_empty_panel_is_not_a_contract_violation():
    """A panel with no accounts yet has nothing to say about field names."""
    from geekvpn.infrastructure.panels.adapters._common import require_a_readable_link

    require_a_readable_link(seen=0, with_link=0, panel="pasarguard")


# -- finding an account when the list omits the link -----------------------


def test_the_account_id_is_read_out_of_the_real_tokens():
    """Both links a customer actually sent. The panels build the token as
    base64 of `v3,<id>,<created>`, so the id is in the link already."""
    from geekvpn.infrastructure.panels.adapters._common import account_id_from_token

    with_dot = "djMsMSwxNzg4NDQxMjYw.Xs1JrAv7_-7Tia_5mhOQv4qI70A4ASA69x8LCWL2Mvw"
    without_dot = "djMsMTE3LDE3ODI3MzkxOTAa062a9db2c"

    assert account_id_from_token(with_dot) == 1
    assert account_id_from_token(without_dot) == 117


def test_a_token_of_another_shape_yields_nothing():
    """The honest answer for a panel that builds them differently - better than
    a number guessed out of arbitrary bytes."""
    from geekvpn.infrastructure.panels.adapters._common import account_id_from_token

    for token in ("", "abc", "not-base64-at-all", "aaaaaaaaaaaaaaaa"):
        assert account_id_from_token(token) is None


def test_ids_are_compared_as_numbers():
    """These panels report `1`, `"1"` and sometimes `1.0` depending on version
    and endpoint; a string comparison misses the account it is looking at."""
    from geekvpn.infrastructure.panels.adapters._common import same_id

    assert same_id({"id": 1}, 1)
    assert same_id({"id": "1"}, 1)
    assert same_id({"id": 1.0}, 1)
    assert not same_id({"id": 2}, 1)
    assert not same_id({"id": None}, 1)
    assert not same_id({"id": "ali"}, 1)


def test_the_id_is_found_under_any_name_these_panels_use():
    """Same reason the link has four spellings: guessing one costs a deploy and
    a customer trying their link again."""
    from geekvpn.infrastructure.panels.adapters._common import same_id

    for key in ("id", "user_id", "uid", "pk"):
        assert same_id({key: 7}, 7)


def test_a_row_with_no_id_at_all_matches_nothing():
    from geekvpn.infrastructure.panels.adapters._common import same_id

    assert not same_id({"username": "ali"}, 1)
