"""Tests for SearchService."""

from __future__ import annotations

from geekvpn.application.support.search_service import SearchQuery
from geekvpn.domain.support.enums import TicketState
from tests.unit.support.fakes import USER_ID
from tests.unit.support.world import World


def test_search_finds_ticket_by_subject():
    w = World()
    w.open(
        subject="\u0645\u0634\u06a9\u0644 \u062f\u0631 \u0627\u062a\u0635\u0627\u0644 \u0628\u0647 \u0633\u0631\u0648\u0631"
    )
    w.open(subject="\u067e\u0631\u062f\u0627\u062e\u062a \u0646\u0627\u0645\u0648\u0641\u0642")
    result = w.search.search(SearchQuery(query="\u0627\u062a\u0635\u0627\u0644"))
    assert result.total == 1
    assert "\u0627\u062a\u0635\u0627\u0644" in result.summaries[0].subject_fa


def test_search_finds_ticket_by_message_body():
    w = World()
    w.open(
        subject="\u062a\u06cc\u06a9\u062a \u0639\u0645\u0648\u0645\u06cc",
        message="\u0633\u0631\u0639\u062a \u062f\u0627\u0646\u0644\u0648\u062f \u0628\u0633\u06cc\u0627\u0631 \u06a9\u0646\u062f \u0627\u0633\u062a",
    )
    result = w.search.search(SearchQuery(query="\u062f\u0627\u0646\u0644\u0648\u062f"))
    assert result.total >= 1


def test_search_too_short_returns_empty():
    w = World()
    w.open()
    result = w.search.search(SearchQuery(query="a"))
    assert result.total == 0
    assert result.summaries == []


def test_search_filtered_by_user():
    w = World()
    w.open(user_id=USER_ID, subject="\u0645\u0634\u06a9\u0644 \u0627\u062a\u0635\u0627\u0644")
    w.open(user_id=9999, subject="\u0645\u0634\u06a9\u0644 \u0627\u062a\u0635\u0627\u0644")
    result = w.search.search(SearchQuery(query="\u0645\u0634\u06a9\u0644", user_id=USER_ID))
    assert all(s.user_id == USER_ID for s in result.summaries)


def test_search_filtered_by_state():
    from tests.unit.support.fakes import AGENT_ID

    w = World()
    w.open(subject="\u0645\u0634\u06a9\u0644 \u0628\u0627\u0632")
    s2 = w.open(subject="\u0645\u0634\u06a9\u0644 \u0628\u0633\u062a\u0647")
    w.tickets.close_ticket(s2.ticket_id, actor_id=AGENT_ID, closed_by_agent=True)
    result = w.search.search(SearchQuery(query="\u0645\u0634\u06a9\u0644", state=TicketState.OPEN))
    assert all(s.state is TicketState.OPEN for s in result.summaries)
