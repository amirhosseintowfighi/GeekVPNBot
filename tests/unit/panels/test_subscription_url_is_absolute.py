"""A subscription link a customer can actually open.

PasarGuard answers with `/sub/<token>` on some versions and a full URL on
others. A relative one reaches the customer as a link that opens nothing, and
they report that as "the VPN is broken" rather than "the link is malformed" -
so it is joined onto the panel's base URL once, in the adapter, rather than at
each of the four places that read it.
"""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.panels.adapters.pasarguard import PasarGuardAdapter
from geekvpn.infrastructure.panels.config import PasarGuardConfig

pytestmark = pytest.mark.unit


def adapter(base_url: str = "https://panel.example.com") -> PasarGuardAdapter:
    instance = object.__new__(PasarGuardAdapter)
    instance._config = PasarGuardConfig(base_url=base_url, username="u", password="p")  # type: ignore[attr-defined]
    return instance


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("/sub/abc", "https://panel.example.com/sub/abc"),
        ("sub/abc", "https://panel.example.com/sub/abc"),
        ("https://cdn.example.com/sub/abc", "https://cdn.example.com/sub/abc"),
        ("http://plain.example.com/sub/abc", "http://plain.example.com/sub/abc"),
    ],
)
def test_a_relative_link_is_made_absolute(stored: str, expected: str) -> None:
    assert adapter()._absolute(stored) == expected


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_nothing_stays_nothing(empty: str | None) -> None:
    """An empty string must not become the panel's own home page - the
    customer would get a link that opens a login form."""
    assert adapter()._absolute(empty) is None


def test_a_trailing_slash_on_the_panel_does_not_double_up() -> None:
    assert (
        adapter("https://panel.example.com/")._absolute("/sub/abc")
        == "https://panel.example.com/sub/abc"
    )
