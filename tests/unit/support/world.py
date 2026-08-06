"""Wired world for support service tests."""

from __future__ import annotations

from geekvpn.application.support.search_service import SearchService
from geekvpn.application.support.template_service import TemplateService
from geekvpn.application.support.ticket_service import OpenTicketRequest, TicketService
from geekvpn.domain.support.enums import TicketCategory, TicketPriority
from tests.unit.support.fakes import (
    EPOCH,
    USER_ID,
    FakeClock,
    FakeEvents,
    FakeIds,
    FakeNotifier,
    FakeTemplateRepository,
    FakeTicketRepository,
)


class World:
    """All collaborators wired together. One instance per test."""

    def __init__(self) -> None:
        self.clock = FakeClock(EPOCH)
        self.ids = FakeIds()
        self.events = FakeEvents()
        self.notifier = FakeNotifier()
        self.ticket_repo = FakeTicketRepository()
        self.template_repo = FakeTemplateRepository()

        self.tickets = TicketService(
            tickets=self.ticket_repo,
            templates=self.template_repo,
            clock=self.clock,
            ids=self.ids,
            events=self.events,
            notifier=self.notifier,
        )
        self.templates = TemplateService(
            templates=self.template_repo,
            clock=self.clock,
            ids=self.ids,
        )
        self.search = SearchService(
            tickets=self.ticket_repo,
            clock=self.clock,
        )

    def open(
        self,
        *,
        user_id=USER_ID,
        subject="\u0645\u0634\u06a9\u0644 \u0627\u062a\u0635\u0627\u0644",
        message="\u0633\u0631\u0648\u06cc\u0633 \u0648\u0635\u0644 \u0646\u0645\u06cc\u200c\u0634\u0648\u062f \u0644\u0637\u0641\u0627\u064b \u0631\u0633\u06cc\u062f\u06af\u06cc \u0631\u0627 \u0628\u0631\u0631\u0633\u06cc \u06a9\u0646\u06cc\u062f",
        category=TicketCategory.CONNECTION,
        priority=TicketPriority.NORMAL,
    ):
        return self.tickets.open_ticket(
            OpenTicketRequest(
                user_id=user_id,
                subject_fa=subject,
                first_message_fa=message,
                category=category,
                priority=priority,
            )
        )
