"""The audit page survives an action it has never heard of.

`_to_domain` called `AuditAction(model.action)`, which raises on anything not
in that one enum. The catalogue records its own `CatalogAuditAction` into the
same column - deliberately, and the docstring on `domain/catalog/audit.py` says
so - so the first time anybody published or archived a category, every
subsequent read of the audit log answered 500.

That is what the panel showed as "خطایی رخ داد. دوباره تلاش کنید."

The general shape matters more than the one enum: an audit log is append-only
history, and a release that adds an action leaves rows an older reader has
never seen. A reader that refuses to show yesterday because it does not
recognise one word of it is the wrong reader.
"""

from __future__ import annotations

import pytest

from geekvpn.domain.audit.entry import AuditAction
from geekvpn.domain.catalog.audit import CatalogAuditAction
from geekvpn.infrastructure.persistence.repositories.audit import _action

pytestmark = pytest.mark.unit


def test_the_action_that_broke_the_page():
    """`catalog.category.state_changed`, exactly as recorded."""
    assert _action(CatalogAuditAction.CATEGORY_STATE_CHANGED.value) == (
        "catalog.category.state_changed"
    )


@pytest.mark.parametrize("action", list(CatalogAuditAction))
def test_no_catalogue_action_can_break_it(action):
    """Every one of these is written through the same recorder."""
    assert _action(action.value) == action.value


def test_a_known_action_still_comes_back_as_the_enum():
    """The fallback must not quietly turn every row into a bare string; the
    labels the panel renders come off the enum."""
    resolved = _action(AuditAction.AUTH_LOGIN_SUCCEEDED.value)

    assert resolved is AuditAction.AUTH_LOGIN_SUCCEEDED


def test_something_from_a_future_release_is_shown_rather_than_refused():
    """A row written by a newer version, read by an older one. It is still a
    fact that happened, and hiding the whole page is not an improvement."""
    assert _action("something.nobody.has.written.yet") == "something.nobody.has.written.yet"


def test_both_kinds_render_the_same_way():
    """The router calls `str()` on it, and the two must be indistinguishable
    on screen - otherwise one kind of row renders as `AuditAction.X`."""
    assert str(_action(AuditAction.AUTH_LOGIN_SUCCEEDED.value)) == "auth.login.succeeded"
    assert str(_action("catalog.category.state_changed")) == "catalog.category.state_changed"
