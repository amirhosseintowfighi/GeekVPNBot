"""Which Telegram accounts an operator alert should reach.

Read from the admin table's own `telegram_id`, so there is no second list of
"people who get notified" to fall out of step with who actually has access.
Suspending an admin therefore stops the alerts at the same moment it stops the
panel, which is the property a separate list cannot have.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from geekvpn.domain.identity.enums import AdminStatus
from geekvpn.infrastructure.persistence.models.identity import AdminModel


class SyncOperatorDirectory:
    def __init__(self, session: Session) -> None:
        self._session = session

    def operator_chat_ids(self) -> Sequence[int]:
        """Active admins who have linked Telegram, and nobody else.

        An admin who never linked their account is not an error and not worth
        a warning on every receipt: they use the panel, and the panel still
        shows the queue.
        """
        stmt = select(AdminModel.telegram_id).where(
            AdminModel.telegram_id.is_not(None),
            AdminModel.status == AdminStatus.ACTIVE.value,
        )
        return [row for row in self._session.execute(stmt).scalars().all() if row]


__all__ = ["SyncOperatorDirectory"]
