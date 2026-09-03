"""User repository."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.domain.identity.enums import Language, UserStatus
from geekvpn.domain.identity.user import User
from geekvpn.infrastructure.persistence.models.identity import UserModel
from geekvpn.infrastructure.persistence.repositories.sync_directory import (
    Person,
    person_of,
)


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        model = await self._session.get(UserModel, user_id)
        return _to_domain(model) if model else None

    async def search(
        self,
        *,
        status: UserStatus | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[User], int]:
        """The customer list for the admin panel, with the unpaged total.

        ``query`` matches the username or either name part. Telegram ids are
        matched exactly when the term is numeric, because a partial id is never
        what an operator means.
        """
        filters: list[ColumnElement[bool]] = []
        if status is not None:
            filters.append(UserModel.status == status.value)
        if query:
            term = f"%{query}%"
            matches: list[ColumnElement[bool]] = [
                UserModel.username.ilike(term),
                UserModel.first_name.ilike(term),
                UserModel.last_name.ilike(term),
            ]
            if query.isdigit():
                matches.append(UserModel.telegram_id == int(query))
            filters.append(or_(*matches))

        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(UserModel).where(*filters)
                )
            ).scalar_one()
        )
        stmt = (
            select(UserModel)
            .where(*filters)
            .order_by(UserModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(row) for row in rows], total

    async def get_by_telegram_id(
        self, telegram_id: int, *, reseller_id: uuid.UUID | None = None
    ) -> User | None:
        """One person, in one shop.

        `reseller_id` is not optional in meaning, only in signature: `None` is
        the platform's own bot, which is a real answer rather than "any shop".
        Matching on the Telegram id alone would hand a reseller's customer the
        account they have with *us* - somebody else's wallet balance and
        subscription list, shown to them under a name they believe belongs to
        the reseller.
        """
        stmt = select(UserModel).where(
            UserModel.telegram_id == telegram_id,
            UserModel.reseller_id.is_(None)
            if reseller_id is None
            else UserModel.reseller_id == reseller_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_domain(model) if model else None

    async def people_by_telegram_ids(self, telegram_ids: Iterable[int]) -> dict[int, Person]:
        """Names for a page of rows that only store an id.

        The same shape as `SyncUserDirectory.by_telegram_ids`, and it builds
        the `Person` through the same function, so the panel cannot show one
        customer under two different names depending on which screen it is.
        """
        wanted = {int(value) for value in telegram_ids}
        if not wanted:
            return {}
        rows = (
            (await self._session.execute(select(UserModel).where(UserModel.telegram_id.in_(wanted))))
            .scalars()
            .all()
        )
        return {row.telegram_id: person_of(row) for row in rows}

    async def list_for_reseller(
        self, reseller_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[Sequence[User], int]:
        """One reseller's customers, and how many they have.

        The count comes back with the page because the first thing a reseller
        looks at is how many people they have, and asking twice is two round
        trips for one screen.
        """
        total = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(UserModel)
                    .where(UserModel.reseller_id == reseller_id)
                )
            ).scalar_one()
        )
        stmt = (
            select(UserModel)
            .where(UserModel.reseller_id == reseller_id)
            .order_by(UserModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(row) for row in rows], total

    async def get_by_referral_code(self, code: str) -> User | None:
        stmt = select(UserModel).where(UserModel.referral_code == code)
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_domain(model) if model else None

    async def add(self, user: User) -> None:
        self._session.add(_to_model(user))
        # Flush, not commit: the unit of work owns the transaction boundary.
        # Flushing here surfaces a unique-violation as a failure of *this*
        # call rather than of some unrelated later one.
        await self._session.flush()

    async def update(self, user: User) -> None:
        model = await self._session.get(UserModel, user.id)
        if model is None:  # pragma: no cover - caller loaded it moments ago
            return
        model.username = user.username
        model.first_name = user.first_name
        model.last_name = user.last_name
        model.preferred_name = user.preferred_name
        model.language = user.language.value
        model.status = user.status.value
        model.is_premium = user.is_premium
        model.photo_url = user.photo_url
        model.referred_by_code = user.referred_by_code
        model.suspended_reason = user.suspended_reason
        model.last_seen_at = user.last_seen_at
        await self._session.flush()


def _to_domain(model: UserModel) -> User:
    return User(
        model.id,
        telegram_id=model.telegram_id,
        reseller_id=None if model.reseller_id is None else str(model.reseller_id),
        referral_code=model.referral_code,
        username=model.username,
        first_name=model.first_name,
        last_name=model.last_name,
        preferred_name=model.preferred_name,
        language=Language(model.language),
        status=UserStatus(model.status),
        is_premium=model.is_premium,
        photo_url=model.photo_url,
        referred_by_code=model.referred_by_code,
        last_seen_at=model.last_seen_at,
        suspended_reason=model.suspended_reason,
        created_at=model.created_at,
    )


def _to_model(user: User) -> UserModel:
    return UserModel(
        id=user.id,
        telegram_id=user.telegram_id,
        reseller_id=None if user.reseller_id is None else uuid.UUID(user.reseller_id),
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        preferred_name=user.preferred_name,
        language=user.language.value,
        status=user.status.value,
        is_premium=user.is_premium,
        photo_url=user.photo_url,
        referral_code=user.referral_code,
        referred_by_code=user.referred_by_code,
        suspended_reason=user.suspended_reason,
        last_seen_at=user.last_seen_at,
    )
