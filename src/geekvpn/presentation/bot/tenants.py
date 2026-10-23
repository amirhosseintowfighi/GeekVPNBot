"""The `Bot` instances belonging to resellers, one per token.

Held per process and built on first use. A deployment with thirty resellers
would otherwise open thirty HTTP sessions at start-up for bots that may see no
traffic all day - and a reseller who configures a bot at noon would not be
served until the next restart.

Cached both ways. A hit avoids a database read and a session setup on every
update; a *miss* is cached too, for a short while, so a stream of updates for a
reseller whose token was removed does not become a query per update.
"""

from __future__ import annotations

import uuid
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.bot.session import telegram_session

logger = get_logger(__name__)

#: How long a "this reseller has no bot" answer is trusted.
#:
#: Short, because the usual cause is a token that was just added and this cache
#: is what would keep it dark. Long enough that a bot removed mid-conversation
#: does not cost a query per retry.
NEGATIVE_TTL_SECONDS = 60.0


class TenantBots:
    def __init__(self, container: Any, *, parse_mode: str = "HTML") -> None:
        self._container = container
        self._parse_mode = parse_mode
        self._bots: dict[uuid.UUID, Bot] = {}
        self._missing: dict[uuid.UUID, float] = {}

    async def bot_for(self, reseller_id: uuid.UUID) -> Bot | None:
        cached = self._bots.get(reseller_id)
        if cached is not None:
            return cached

        now = self._container.clock.now().timestamp()
        missed_at = self._missing.get(reseller_id)
        if missed_at is not None and now - missed_at < NEGATIVE_TTL_SECONDS:
            return None

        token = await self._load_token(reseller_id)
        if not token:
            self._missing[reseller_id] = now
            return None

        bot = Bot(
            token=token,
            session=telegram_session(),
            default=DefaultBotProperties(parse_mode=self._parse_mode),
        )
        self._bots[reseller_id] = bot
        self._missing.pop(reseller_id, None)
        logger.info("bot.tenant_loaded", reseller=reseller_id.hex)
        return bot

    async def forget(self, reseller_id: uuid.UUID) -> None:
        """Drop a cached bot, so the next update reloads its token.

        Needed when a reseller replaces their token: the old `Bot` would keep
        answering with a credential Telegram no longer honours.
        """
        bot = self._bots.pop(reseller_id, None)
        self._missing.pop(reseller_id, None)
        if bot is not None:
            await bot.session.close()

    async def active(self) -> dict[uuid.UUID, Bot]:
        """Every active reseller's bot, built and cached.

        For the paths that cannot wait for an update to arrive before knowing
        a bot exists: polling has to ask each one for its updates, and webhook
        start-up re-points each one at us. A bot dropped from the answer -
        suspended reseller, removed token - is closed here too.
        """
        async with self._container.session_factory() as session:
            from geekvpn.infrastructure.di.scope import RequestScope

            scope = RequestScope(container=self._container, session=session)
            rows = await scope.resellers.with_bots()

        wanted = {reseller_id: token for reseller_id, token, _ in rows if token}
        for reseller_id in list(self._bots):
            if reseller_id not in wanted:
                await self.forget(reseller_id)
        for reseller_id, token in wanted.items():
            if reseller_id not in self._bots:
                self._bots[reseller_id] = Bot(
                    token=token,
                    session=telegram_session(),
                    default=DefaultBotProperties(parse_mode=self._parse_mode),
                )
                self._missing.pop(reseller_id, None)
        return dict(self._bots)

    async def close(self) -> None:
        for bot in self._bots.values():
            await bot.session.close()
        self._bots.clear()

    async def _load_token(self, reseller_id: uuid.UUID) -> str | None:
        async with self._container.session_factory() as session:
            from geekvpn.infrastructure.di.scope import RequestScope

            scope = RequestScope(container=self._container, session=session)
            reseller = await scope.resellers.get(reseller_id)
            # A suspended or closed reseller's bot stops answering. Their
            # existing customers keep the service they paid for - that is the
            # subscription's business, not this one's - but no new conversation
            # is served under a name we have stopped supplying.
            if reseller is None or not reseller.status.may_provision:
                return None
            return await scope.resellers.bot_token(reseller_id)


__all__ = ["NEGATIVE_TTL_SECONDS", "TenantBots"]
