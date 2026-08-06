"""Tests for TemplateService."""

from __future__ import annotations

import pytest

from geekvpn.domain.base.errors import ValidationError
from geekvpn.domain.support.enums import TicketCategory
from geekvpn.domain.support.errors import TemplateNotFound
from tests.unit.support.world import World


def test_create_template_returns_a_view():
    w = World()
    view = w.templates.create(
        title_fa="\u067e\u0627\u0633\u062e \u0622\u0645\u0627\u062f\u0647 \u0627\u062a\u0635\u0627\u0644",
        body_fa="\u0644\u0637\u0641\u0627\u064b \u0628\u0631\u0646\u0627\u0645\u0647 \u0631\u0627 \u062f\u0648\u0628\u0627\u0631\u0647 \u0646\u0635\u0628 \u06a9\u0646\u06cc\u062f \u0648 \u0627\u0631\u062a\u0628\u0627\u0637 \u0631\u0627 \u0628\u0631\u0631\u0633\u06cc \u0646\u0645\u0627\u06cc\u06cc\u062f.",
    )
    assert view.template_id is not None
    assert view.is_active is True
    assert view.use_count == 0


def test_template_with_no_categories_applies_to_all():
    w = World()
    view = w.templates.create(
        title_fa="\u0639\u0645\u0648\u0645\u06cc",
        body_fa="\u0645\u0634\u06a9\u0644 \u0634\u0645\u0627 \u0628\u0631\u0631\u0633\u06cc \u0634\u062f \u0628\u0632\u0648\u062f\u06cc \u0628\u0627 \u0634\u0645\u0627 \u062a\u0645\u0627\u0633 \u062e\u0648\u0627\u0647\u06cc\u0645 \u06af\u0631\u0641\u062a.",
    )
    active = w.templates.list_active(category=TicketCategory.PAYMENT)
    assert any(t.template_id == view.template_id for t in active)


def test_template_scoped_to_category_is_not_shown_for_others():
    w = World()
    w.templates.create(
        title_fa="\u0628\u0627\u0632\u067e\u0631\u062f\u0627\u062e\u062a",
        body_fa="\u0645\u0628\u0644\u063a \u067e\u0631\u062f\u0627\u062e\u062a\u06cc \u0634\u062f\u0647 \u0628\u0647 \u06a9\u06cc\u0641 \u067e\u0648\u0644 \u0628\u0631\u0645\u06cc\u200c\u06af\u0631\u062f\u062f.",
        categories=[TicketCategory.PAYMENT],
    )
    connection_templates = w.templates.list_active(category=TicketCategory.CONNECTION)
    assert connection_templates == []


def test_deactivated_template_is_excluded_from_list():
    w = World()
    view = w.templates.create(
        title_fa="\u0642\u062f\u06cc\u0645\u06cc",
        body_fa="\u0627\u06cc\u0646 \u067e\u0627\u0633\u062e \u062f\u06cc\u06af\u0631 \u0645\u0646\u0633\u0648\u062e\u062e \u0634\u062f\u0647 \u0627\u0633\u062a.",
    )
    w.templates.deactivate(view.template_id)
    assert w.templates.list_active() == []


def test_reactivating_a_template_puts_it_back_in_the_list():
    w = World()
    view = w.templates.create(
        title_fa="\u0628\u0647 \u0632\u0648\u062f\u06cc",
        body_fa="\u067e\u0627\u0633\u062e \u0633\u0631\u06cc\u0639 \u0628\u0631\u0627\u06cc \u062a\u06cc\u06a9\u062a \u06cc\u0627\u0641\u062a \u0634\u062f\u0647",
    )
    w.templates.deactivate(view.template_id)
    w.templates.activate(view.template_id)
    assert len(w.templates.list_active()) == 1


def test_update_changes_title_and_body():
    w = World()
    view = w.templates.create(
        title_fa="\u0639\u0646\u0648\u0627\u0646 \u0627\u0648\u0644",
        body_fa="\u0645\u062a\u0646 \u0627\u0648\u0644 \u06a9\u0647 \u062a\u063a\u06cc\u06cc\u0631 \u0645\u06cc\u200c\u06a9\u0646\u062f",
    )
    updated = w.templates.update(
        view.template_id,
        title_fa="\u0639\u0646\u0648\u0627\u0646 \u062a\u063a\u06cc\u06cc\u0631 \u06cc\u0627\u0641\u062a\u0647",
    )
    assert (
        updated.title_fa
        == "\u0639\u0646\u0648\u0627\u0646 \u062a\u063a\u06cc\u06cc\u0631 \u06cc\u0627\u0641\u062a\u0647"
    )


def test_too_short_body_raises():
    w = World()
    with pytest.raises(ValidationError):
        w.templates.create(title_fa="\u062a\u0633\u062a", body_fa="\u06a9\u0648\u062a\u0627\u0647")


def test_delete_removes_from_list():
    w = World()
    view = w.templates.create(
        title_fa="\u0645\u0648\u0642\u062a",
        body_fa="\u0628\u0647 \u0632\u0648\u062f\u06cc \u062d\u0630\u0641 \u0645\u06cc\u200c\u0634\u0648\u062f",
    )
    w.templates.delete(view.template_id)
    assert w.templates.list_active() == []


def test_get_nonexistent_template_raises():
    w = World()
    with pytest.raises(TemplateNotFound):
        w.templates.get("no-such-template")
