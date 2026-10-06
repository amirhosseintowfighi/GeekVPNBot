"""Where the app's FCM tokens live, and the ``AppPush`` that uses them.

Keyed by Telegram id, the same key tickets and notifications use, so a support
reply can find the customer's phones without a join through users. One
customer can have several phones; one token belongs to one install.
"""

from __future__ import annotations

from datetime import datetime

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from geekvpn.infrastructure.persistence.models.identity import AppPushTokenModel
from geekvpn.infrastructure.push.fcm import FcmClient, SendOutcome

logger = structlog.stdlib.get_logger(__name__)

#: Longest token FCM hands out is well under this; anything longer is not one.
MAX_TOKEN_LENGTH = 512
#: A customer with more installs than this has stale ones; the oldest are dropped.
MAX_TOKENS_PER_CUSTOMER = 5


def register_token(session: Session, *, token: str, telegram_id: int, now: datetime) -> None:
    """Upsert: a token that moved to another account (re-login) moves with it."""
    session.execute(
        insert(AppPushTokenModel)
        .values(token=token, telegram_id=telegram_id, updated_at=now)
        .on_conflict_do_update(
            index_elements=[AppPushTokenModel.token],
            set_={"telegram_id": telegram_id, "updated_at": now},
        )
    )
    stale = session.scalars(
        select(AppPushTokenModel.token)
        .where(AppPushTokenModel.telegram_id == telegram_id)
        .order_by(AppPushTokenModel.updated_at.desc())
        .offset(MAX_TOKENS_PER_CUSTOMER)
    ).all()
    if stale:
        session.execute(delete(AppPushTokenModel).where(AppPushTokenModel.token.in_(stale)))


def forget_token(session: Session, *, token: str, telegram_id: int) -> None:
    """Logout: only the caller's own token, so nobody can unsubscribe someone else."""
    session.execute(
        delete(AppPushTokenModel).where(
            AppPushTokenModel.token == token, AppPushTokenModel.telegram_id == telegram_id
        )
    )


class SqlAppPush:
    """``application.notifications.ports.AppPush`` over FCM and the token table."""

    def __init__(self, *, session: Session, fcm: FcmClient) -> None:
        self._session = session
        self._fcm = fcm

    def notify(self, telegram_id: int, data: dict[str, str]) -> None:
        try:
            tokens = self._session.scalars(
                select(AppPushTokenModel.token).where(AppPushTokenModel.telegram_id == telegram_id)
            ).all()
            gone = [t for t in tokens if self._fcm.send(t, data) is SendOutcome.UNREGISTERED]
            if gone:
                # A nested transaction, so failing to clean up cannot take the
                # caller's reply down with it.
                with self._session.begin_nested():
                    self._session.execute(
                        delete(AppPushTokenModel).where(AppPushTokenModel.token.in_(gone))
                    )
        except Exception as exc:
            logger.warning("push.notify_failed", error=type(exc).__name__)


__all__ = ["MAX_TOKEN_LENGTH", "SqlAppPush", "forget_token", "register_token"]
