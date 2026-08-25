"""A queue row must name a person, not an integer.

Tickets, payments and orders all record who they belong to as a Telegram id,
because that is what the bot knows and the number never changes. The panel
rendered the number, so identifying a customer meant opening another screen -
which is what the support team was doing, per ticket.
"""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.persistence.repositories.sync_directory import _person

pytestmark = pytest.mark.unit


class Row:
    def __init__(self, **fields: object) -> None:
        self.telegram_id = fields.get("telegram_id", 87791922)
        self.username = fields.get("username")
        self.first_name = fields.get("first_name")
        self.last_name = fields.get("last_name")


def test_both_names_are_joined() -> None:
    person = _person(Row(first_name="امیرحسین", last_name="توفیقی"))

    assert person.display_name == "امیرحسین توفیقی"


def test_a_missing_surname_does_not_leave_a_trailing_space() -> None:
    person = _person(Row(first_name="امیرحسین"))

    assert person.display_name == "امیرحسین"


def test_the_handle_stands_in_when_there_is_no_name() -> None:
    person = _person(Row(username="geekvpn"))

    assert person.display_name == "geekvpn"


def test_the_id_stands_in_when_there_is_nothing_at_all() -> None:
    """A row labelled "None" is worse than one labelled with something an
    agent can paste into a search box."""
    person = _person(Row(telegram_id=555))

    assert person.display_name == "555"


def test_the_handle_is_formatted_once_and_in_one_place() -> None:
    assert _person(Row(username="geekvpn")).handle == "@geekvpn"
    assert _person(Row(first_name="x")).handle is None
