"""Tests for support enums."""

from __future__ import annotations

from geekvpn.domain.support.enums import (
    MessageKind,
    TicketCategory,
    TicketPriority,
    TicketState,
)


def test_priority_sla_minutes_are_ordered():
    assert (
        TicketPriority.URGENT.sla_minutes()
        < TicketPriority.HIGH.sla_minutes()
        < TicketPriority.NORMAL.sla_minutes()
        < TicketPriority.LOW.sla_minutes()
    )


def test_every_priority_has_a_persian_label():
    for p in TicketPriority:
        assert len(p.label_fa()) > 0


def test_every_category_has_a_persian_label():
    for c in TicketCategory:
        assert len(c.label_fa()) > 0


def test_open_state_awaits_agent():
    assert TicketState.OPEN.awaits_agent() is True
    assert TicketState.WAITING_USER.awaits_agent() is False


def test_closed_state_is_terminal():
    assert TicketState.CLOSED.is_terminal() is True
    assert TicketState.OPEN.is_terminal() is False


def test_note_and_status_change_are_internal():
    assert MessageKind.NOTE.is_internal() is True
    assert MessageKind.STATUS_CHANGE.is_internal() is True
    assert MessageKind.CUSTOMER.is_internal() is False
    assert MessageKind.SUPPORT.is_internal() is False


def test_customer_and_support_messages_are_visible_to_customer():
    assert MessageKind.CUSTOMER.is_visible_to_customer() is True
    assert MessageKind.SUPPORT.is_visible_to_customer() is True
    assert MessageKind.NOTE.is_visible_to_customer() is False
