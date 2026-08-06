"""Search service — full-text search across tickets and message bodies.

The repository does the heavy lifting (Postgres tsvector, SQLite FTS, or a
simple ILIKE depending on the environment). The service normalises the query
and adds business constraints before delegating.
"""

from __future__ import annotations

from dataclasses import dataclass

from geekvpn.application.support.ports import Clock, TicketRepository
from geekvpn.application.support.ticket_service import TicketSummary
from geekvpn.domain.support.enums import TicketCategory, TicketPriority, TicketState

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 200


@dataclass(frozen=True, slots=True)
class SearchQuery:
    query: str
    user_id: int | None = None
    state: TicketState | None = None
    category: TicketCategory | None = None
    priority: TicketPriority | None = None
    limit: int = 25
    offset: int = 0


@dataclass(frozen=True, slots=True)
class SearchResult:
    summaries: list[TicketSummary]
    total: int
    query: str


class SearchService:
    def __init__(self, *, tickets: TicketRepository, clock: Clock) -> None:
        self._tickets = tickets
        self._clock = clock

    def search(self, query: SearchQuery) -> SearchResult:
        normalized = query.query.strip()
        if len(normalized) < MIN_QUERY_LENGTH:
            return SearchResult(summaries=[], total=0, query=normalized)
        if len(normalized) > MAX_QUERY_LENGTH:
            normalized = normalized[:MAX_QUERY_LENGTH]

        now = self._clock.now()
        tickets = self._tickets.search(
            normalized,
            user_id=query.user_id,
            state=query.state,
            limit=query.limit,
            offset=query.offset,
        )
        return SearchResult(
            summaries=[TicketSummary.from_ticket(t, now) for t in tickets],
            total=len(tickets),  # Exact count; repos may return a cursor count.
            query=normalized,
        )


__all__ = ["MIN_QUERY_LENGTH", "SearchQuery", "SearchResult", "SearchService"]
