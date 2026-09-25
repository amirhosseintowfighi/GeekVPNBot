"""Customers' app logins (see `AppPasswordLogin`).

`save` is one upsert on the customer's row. The username's unique constraint
is what decides a race for the same name; the write runs in a savepoint so the
loser gets `False` and the surrounding transaction stays usable.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.domain.identity.app_credentials import AppCredential
from geekvpn.infrastructure.persistence.models.identity import AppCredentialModel

_Row = AppCredentialModel


class SqlAlchemyAppCredentialRepository:
    """Implements `AppCredentialRepository` over PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def get_by_user(self, user_id: uuid.UUID) -> AppCredential | None:
        row = await self._db.get(_Row, user_id)
        return row.to_domain() if row is not None else None

    async def get_by_username(self, username: str) -> AppCredential | None:
        row = (
            await self._db.execute(select(_Row).where(_Row.username == username))
        ).scalar_one_or_none()
        return row.to_domain() if row is not None else None

    async def save(self, credential: AppCredential) -> bool:
        values = {
            "username": credential.username,
            "password_hash": credential.password_hash,
            "updated_at": credential.updated_at,
        }
        stmt = (
            insert(_Row)
            .values(user_id=credential.user_id, **values)
            .on_conflict_do_update(index_elements=[_Row.user_id], set_=values)
        )
        try:
            async with self._db.begin_nested():
                await self._db.execute(stmt)
        except IntegrityError:
            # uq_app_credentials_username: another customer has this name.
            return False
        # The identity map may hold the old row from an earlier `get`.
        self._db.expire_all()
        return True

    async def delete(self, user_id: uuid.UUID) -> bool:
        result = await self._db.execute(delete(_Row).where(_Row.user_id == user_id))
        return bool(getattr(result, "rowcount", 0))
