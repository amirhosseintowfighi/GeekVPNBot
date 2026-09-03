"""A name the customer chose is not overwritten by Telegram.

The bot lets somebody say what to call them, and it worked - until their next
/start. `refresh_profile` runs on every authentication and treats the Telegram
payload as authoritative, and the chosen name was being written into
`first_name`, which is one of the fields that payload owns. So the name
reverted, silently, to whatever their Telegram account says.
"""

from __future__ import annotations

import uuid

import pytest

from geekvpn.domain.identity.user import User

pytestmark = pytest.mark.unit


def _user(**kwargs: object) -> User:
    return User(
        uuid.uuid4(),
        telegram_id=42,
        referral_code="ABC12345",
        **kwargs,  # type: ignore[arg-type]
    )


def test_a_chosen_name_survives_the_next_authentication():
    """The bug, exactly: choose a name, then /start."""
    user = _user(first_name="Ali", username="ali")
    user.set_preferred_name("آقای مهندس")

    user.refresh_profile(username="ali", first_name="Ali", last_name=None)

    assert user.display_name == "آقای مهندس"


def test_the_telegram_name_is_still_kept_underneath():
    """Choosing a nickname must not lose what Telegram says.

    An operator searching for a customer by their real Telegram name has to
    keep finding them.
    """
    user = _user(first_name="Ali", last_name="Rezaei")
    user.set_preferred_name("مهندس")

    assert user.first_name == "Ali"
    assert user.last_name == "Rezaei"


def test_clearing_the_chosen_name_falls_back_to_telegram():
    user = _user(first_name="Ali")
    user.set_preferred_name("مهندس")
    user.set_preferred_name("")

    assert user.display_name == "Ali"


def test_whitespace_is_not_a_name():
    """Otherwise a stray space becomes a display name of one space, and the
    customer appears in every list as a blank row."""
    user = _user(first_name="Ali")
    user.set_preferred_name("   ")

    assert user.display_name == "Ali"


def test_someone_with_no_telegram_name_at_all_still_has_one():
    user = _user(username="ali")

    assert user.display_name == "@ali"
