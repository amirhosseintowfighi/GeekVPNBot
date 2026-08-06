"""User repository."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.domain.identity.enums import Language, UserStatus
from geekvpn.domain.identity.user import User
from geekvpn.infrastructure.persistence.models.identity import UserModel


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        model = await self._session.get(UserModel, user_id)
        return _to_domain(model) if model else None

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = select(UserModel).where(UserModel.telegram_id == telegram_id)
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_domain(model) if model else None

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
        referral_code=model.referral_code,
        username=model.username,
        first_name=model.first_name,
        last_name=model.last_name,
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
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language=user.language.value,
        status=user.status.value,
        is_premium=user.is_premium,
        photo_url=user.photo_url,
        referral_code=user.referral_code,
        referred_by_code=user.referred_by_code,
        suspended_reason=user.suspended_reason,
        last_seen_at=user.last_seen_at,
    )
