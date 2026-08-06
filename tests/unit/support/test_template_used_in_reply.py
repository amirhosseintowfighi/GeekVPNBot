"""Tests: reply templates used inside agent replies."""

from __future__ import annotations

from geekvpn.application.support.ticket_service import ReplyRequest
from tests.unit.support.fakes import AGENT_ID
from tests.unit.support.world import World


def test_agent_reply_using_template_records_template_id():
    w = World()
    tmpl = w.templates.create(
        title_fa="\u067e\u0627\u0633\u062e \u0622\u0645\u0627\u062f\u0647",
        body_fa="\u0644\u0637\u0641\u0627\u064b \u0628\u0631\u0646\u0627\u0645\u0647 \u0631\u0627 \u0631\u0648\u06cc \u062f\u0633\u062a\u06af\u0627\u0647 \u062f\u06cc\u06af\u0631\u06cc \u0646\u0635\u0628 \u06a9\u0646\u06cc\u062f.",
    )
    summary = w.open()
    msg = w.tickets.agent_reply(
        ReplyRequest(
            ticket_id=summary.ticket_id,
            body_fa="",  # empty body → service uses template text
            author_id=AGENT_ID,
            template_id=tmpl.template_id,
        )
    )
    assert msg.template_id == tmpl.template_id
    assert len(msg.body_fa) > 0  # template body was injected


def test_using_a_template_increments_use_count():
    w = World()
    tmpl = w.templates.create(
        title_fa="\u067e\u0631\u0645\u0635\u0631\u0641",
        body_fa="\u0627\u06cc\u0646 \u067e\u0627\u0633\u062e \u0628\u0633\u06cc\u0627\u0631 \u0627\u0633\u062a\u0641\u0627\u062f\u0647 \u0645\u06cc\u200c\u0634\u0648\u062f",
    )
    summary = w.open()
    w.tickets.agent_reply(
        ReplyRequest(
            ticket_id=summary.ticket_id,
            body_fa="",
            author_id=AGENT_ID,
            template_id=tmpl.template_id,
        )
    )
    updated_tmpl = w.templates.get(tmpl.template_id)
    assert updated_tmpl.use_count == 1


def test_nonexistent_template_falls_back_to_body_text():
    w = World()
    summary = w.open()
    body = "\u067e\u0627\u0633\u062e \u0628\u062f\u0648\u0646 \u0642\u0627\u0644\u0628"
    msg = w.tickets.agent_reply(
        ReplyRequest(
            ticket_id=summary.ticket_id,
            body_fa=body,
            author_id=AGENT_ID,
            template_id="no-such-template",
        )
    )
    assert msg.body_fa == body
    assert msg.template_id is None  # graceful: no broken link stored
