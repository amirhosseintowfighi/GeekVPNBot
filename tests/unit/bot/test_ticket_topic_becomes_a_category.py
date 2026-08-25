"""A ticket's topic must reach the field the agent queue filters on.

The bot sends a category key - "connection" - and it went straight into
`subject_fa`, so an agent saw a Latin-script word where the subject should be
and `category` stayed OTHER on every ticket the platform had ever opened. The
queue filters on `category`, so filtering by "connection problems" returned
nothing while the queue was full of them.

The Mini App sends free text through the same call, which matches no category
and already is the subject. Both arrive at one function, so both are pinned
here.
"""

from __future__ import annotations

import pytest

from geekvpn.domain.support.enums import TicketCategory
from geekvpn.infrastructure.bot.sync_readers import _categorise

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("category", list(TicketCategory))
def test_every_category_key_is_recognised(category: TicketCategory) -> None:
    """Including any added later, which is the point of parametrising."""
    resolved, subject = _categorise(category.value)

    assert resolved is category
    assert subject == category.label_fa()


def test_the_subject_is_persian_not_the_key() -> None:
    _, subject = _categorise("connection")

    assert subject != "connection"
    assert any("؀" <= character <= "ۿ" for character in subject)


def test_free_text_is_kept_as_the_subject() -> None:
    """The Mini App's path. Guessing a category from prose would be worse than
    admitting we do not know."""
    category, subject = _categorise("وصل نمی‌شوم به آلمان")

    assert category is TicketCategory.OTHER
    assert subject == "وصل نمی‌شوم به آلمان"
