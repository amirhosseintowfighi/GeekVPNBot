"""Every error the API returns carries Persian copy the clients can render."""

from __future__ import annotations

import pathlib
import re

from geekvpn.presentation.api.text_fa import GENERIC, MESSAGES, persian_for

_DOMAIN = pathlib.Path("src/geekvpn/domain")


def _declared_codes() -> set[str]:
    return {
        match.group(1)
        for path in _DOMAIN.rglob("*.py")
        # `code: str = "domain_error"` on the base class carries an
        # annotation the subclasses drop; both spellings are real codes.
        for match in re.finditer(
            r'^\s+code(?:: str)? = "([a-z_]+)"', path.read_text(encoding="utf-8"), re.M
        )
    }


def test_every_domain_error_code_has_persian_copy() -> None:
    missing = _declared_codes() - set(MESSAGES)

    assert not missing, f"domain codes with no Persian copy: {sorted(missing)}"


def test_the_copy_table_names_no_code_that_no_longer_exists() -> None:
    """Checked from both directions on purpose. A table that is only ever
    added to accumulates entries for errors that were renamed years ago, and
    then reads as coverage it does not have."""
    stale = set(MESSAGES) - _declared_codes()

    assert not stale, f"copy for codes no error declares: {sorted(stale)}"


def test_an_unknown_code_falls_back_rather_than_raising() -> None:
    assert persian_for("something_new_and_unmapped") == GENERIC


def test_no_copy_leaves_the_reader_without_a_next_step() -> None:
    """The house rule from the bot's text module: never a bare "an error
    occurred". Every sentence says what happened."""
    assert all(text.strip().endswith((".", "؟")) for text in MESSAGES.values())
    assert all(len(text) > 10 for text in MESSAGES.values())
