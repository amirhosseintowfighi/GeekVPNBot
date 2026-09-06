"""A panel's own answer is not always the link a customer can open.

On a split setup the API lives on one host and subscriptions are served from
another - `panel.doping.games:8443` versus `panel2.hostcheap.top` - and the
panel builds its links from the host it was configured with. Handing the
customer that answer gives them a link to a host that does not serve them, and
the failure is indistinguishable from a broken service.

The same field settles the other question. Once two panels each hold an
account called `amir`, a username identifies nothing; the host in the pasted
link is what says which panel it came from.
"""

from __future__ import annotations

import pytest

from geekvpn.application.provisioning.links import host_of, public_link

pytestmark = pytest.mark.unit

API = "https://panel.doping.games:8443"
SUB = "https://panel2.hostcheap.top"
TOKEN = "djMsMSwxNzg4NDQxMjYw.Xs1JrAv7"


def test_the_panels_own_host_is_swapped_for_the_public_one():
    assert (
        public_link(f"{API}/sub/{TOKEN}", SUB) == f"{SUB}/sub/{TOKEN}"
    )


def test_the_token_survives_the_rewrite():
    """The path is the account. Rewriting more than the origin loses it."""
    assert public_link(f"{API}/sub/{TOKEN}/", SUB).endswith(f"/sub/{TOKEN}/")


def test_a_query_string_is_kept():
    """Clients append format hints, and some panels issue them."""
    assert public_link(f"{API}/sub/{TOKEN}?format=v2ray", SUB).endswith("?format=v2ray")


def test_a_node_without_a_separate_host_is_left_alone():
    """The ordinary case, and the default. Nothing should change for an
    operator who has never heard of this field."""
    link = f"{API}/sub/{TOKEN}"

    assert public_link(link, None) == link
    assert public_link(link, "") == link


def test_a_bare_hostname_is_accepted():
    """An operator typing `sub.example.com` means https, and a field that
    silently ignored the entry would be worse than one that rejected it."""
    assert public_link(f"{API}/sub/{TOKEN}", "sub.example.com") == f"https://sub.example.com/sub/{TOKEN}"


def test_a_port_on_the_public_host_is_honoured():
    assert public_link(f"{API}/sub/{TOKEN}", "https://sub.example.com:2096").startswith(
        "https://sub.example.com:2096/"
    )


def test_a_useless_base_degrades_to_the_panels_answer():
    """A typo must leave the customer with the panel's link, never with a link
    that has no host at all - one is wrong on a split setup, the other is
    wrong everywhere."""
    link = f"{API}/sub/{TOKEN}"

    assert public_link(link, "   ") == link
    assert public_link(link, "https://") == link


def test_nothing_in_nothing_out():
    assert public_link(None, SUB) is None
    assert public_link("", SUB) == ""


def test_a_link_with_no_host_is_not_given_one():
    """Some panels report `/sub/<token>` relative. Inventing a host here would
    hand the customer a link built on a guess."""
    assert public_link(f"/sub/{TOKEN}", SUB) == f"/sub/{TOKEN}"


# -- host_of ---------------------------------------------------------------


def test_the_port_is_part_of_the_host():
    """Two panels on one machine differ only by port."""
    assert host_of("https://panel.example.com:8443/sub/x") == "panel.example.com:8443"
    assert host_of("https://panel.example.com/sub/x") == "panel.example.com"


def test_case_does_not_make_it_a_different_server():
    assert host_of("https://Panel.Example.COM/sub/x") == "panel.example.com"


def test_a_pasted_link_without_a_scheme_still_has_a_host():
    """Customers paste what they were sent, and that is sometimes scheme-less."""
    assert host_of("panel2.hostcheap.top/sub/abc") == "panel2.hostcheap.top"


def test_no_host_is_the_empty_string_not_a_crash():
    assert host_of("") == ""
    assert host_of("just-a-token") == "just-a-token"
