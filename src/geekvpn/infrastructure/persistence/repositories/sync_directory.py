"""Names for Telegram ids, in bulk.

A ticket, a payment and an order all record who they belong to as a Telegram
id, because that is what the bot knows and the number never changes. An
operator reading a queue needs a person, and looking each one up by hand is
what the support team was doing.

One query for a whole page, not one per row: a queue of twenty-five otherwise
becomes twenty-six round trips, and the panel already renders in one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from geekvpn.infrastructure.persistence.models.identity import UserModel


@dataclass(frozen=True, slots=True)
class Person:
    """Enough to address someone, and nothing more.

    Deliberately not the whole user: this is read to label a row in a queue,
    and every extra field is one more thing to keep out of a support agent's
    view of a customer they have no reason to see in full.
    """

    telegram_id: int
    display_name: str
    username: str | None

    @property
    def handle(self) -> str | None:
        return f"@{self.username}" if self.username else None


class SyncUserDirectory:
    def __init__(self, session: Session) -> None:
        self._session = session

    def by_telegram_ids(self, telegram_ids: Iterable[int]) -> dict[int, Person]:
        wanted = {int(value) for value in telegram_ids}
        if not wanted:
            return {}

        rows = (
            self._session.execute(select(UserModel).where(UserModel.telegram_id.in_(wanted)))
            .scalars()
            .all()
        )
        return {row.telegram_id: _person(row) for row in rows}


def _person(row: UserModel) -> Person:
    parts = [part for part in (row.first_name, row.last_name) if part]
    return Person(
        telegram_id=row.telegram_id,
        # Falls back to the handle, then to the id. A row labelled "None" is
        # worse than one labelled with a number an agent can search for.
        display_name=" ".join(parts) or (row.username or str(row.telegram_id)),
        username=row.username,
    )


__all__ = ["Person", "SyncUserDirectory"]
