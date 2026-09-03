"""Who the join gate lets through.

The rule is small and the consequences of getting it wrong are not: too strict
and a paying customer cannot reach a service they already bought, too loose and
the requirement means nothing.
"""

from __future__ import annotations

import asyncio

import pytest

from geekvpn.application.platform.channel_gate import RequiredChannel, missing_channels

pytestmark = pytest.mark.unit

NEWS = RequiredChannel(id="1", chat_ref="@geeknews", title_fa="اطلاع‌رسانی")
VIP = RequiredChannel(id="2", chat_ref="-1001234567890", title_fa="ویژه",
                      invite_url="https://t.me/+abc")


def _gate(channels, answers):
    async def is_member(chat_ref: str, telegram_id: int) -> bool | None:
        return answers[chat_ref]

    return asyncio.run(missing_channels(channels, telegram_id=7, is_member=is_member))


def test_a_member_of_everything_is_let_through():
    assert _gate([NEWS, VIP], {"@geeknews": True, "-1001234567890": True}) == []


def test_one_channel_short_is_still_short():
    """All of them, not any of them."""
    missing = _gate([NEWS, VIP], {"@geeknews": True, "-1001234567890": False})

    assert missing == [VIP]


def test_every_missing_channel_is_named():
    """Telling somebody they are missing "a channel" makes them guess."""
    missing = _gate([NEWS, VIP], {"@geeknews": False, "-1001234567890": False})

    assert missing == [NEWS, VIP]


def test_a_channel_we_cannot_check_does_not_block_anybody():
    """`None` means the bot is not an admin there, or the channel is gone.

    Treating that as "not joined" locks every customer out of a working shop
    over a misconfiguration they can neither see nor fix.
    """
    assert _gate([NEWS], {"@geeknews": None}) == []


def test_an_uncheckable_channel_does_not_excuse_a_missing_one():
    """The lenient case must not become a way through the gate."""
    missing = _gate([NEWS, VIP], {"@geeknews": None, "-1001234567890": False})

    assert missing == [VIP]


def test_no_channels_configured_means_no_gate():
    assert _gate([], {}) == []


def test_a_public_channel_gets_a_link_from_its_name():
    assert NEWS.url == "https://t.me/geeknews"


def test_an_explicit_invite_wins():
    """A private channel has no `@name` to open, and an operator who supplied a
    link meant that link."""
    assert VIP.url == "https://t.me/+abc"


def test_a_private_channel_with_no_invite_offers_no_button():
    """Better than a button that goes nowhere. The API refuses to store this,
    so it should not exist - but the rendering must not invent a link."""
    orphan = RequiredChannel(id="3", chat_ref="-100999", title_fa="بی‌لینک")

    assert orphan.url is None
