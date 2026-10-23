"""Polling: how the bot keeps working when Telegram cannot reach the server.

During an Iranian international outage no webhook arrives, but outbound
through the SOCKS5 proxy still works. These pin what makes polling safe to
switch on mid-outage: nothing queued is dropped, reseller bots are served as
their reseller's shop, a failing proxy is retried rather than fatal, and
switching back to webhooks restores the resellers' webhooks too.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from aiogram.types import Update

from geekvpn.presentation.bot.polling import UpdatePoller

RESELLER = uuid.UUID("0f0e0d0c-0b0a-0908-0706-050403020100")


class FakeBot:
    def __init__(self, batches: list[list[Update] | Exception]) -> None:
        self._batches = batches
        self.deleted: list[dict[str, Any]] = []
        self.offsets: list[int | None] = []
        self.webhooks: list[dict[str, Any]] = []

    async def delete_webhook(self, **kwargs: Any) -> bool:
        self.deleted.append(kwargs)
        return True

    async def get_updates(self, *, offset: int | None = None, **_: Any) -> list[Update]:
        self.offsets.append(offset)
        if self._batches:
            batch = self._batches.pop(0)
            if isinstance(batch, Exception):
                raise batch
            return batch
        await asyncio.sleep(3600)
        return []

    async def set_webhook(self, **kwargs: Any) -> bool:
        self.webhooks.append(kwargs)
        return True


class FakeDispatcher:
    def __init__(self) -> None:
        self.fed: list[tuple[FakeBot, int, dict[str, Any]]] = []

    async def feed_update(self, *, bot: FakeBot, update: Update, **extra: Any) -> None:
        self.fed.append((bot, update.update_id, extra))


async def _no_wait(_: float) -> None:
    await asyncio.sleep(0)


async def _run(poller: UpdatePoller, until: Any) -> None:
    task = asyncio.create_task(poller.run())
    for _ in range(200):
        await asyncio.sleep(0)
        if until():
            break
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_each_bot_drops_its_webhook_without_dropping_queued_updates() -> None:
    main, tenant = FakeBot([]), FakeBot([])

    async def tenants() -> dict[uuid.UUID, Any]:
        return {RESELLER: tenant}

    poller = UpdatePoller(FakeDispatcher(), main_bot=main, tenants=tenants, sleep=_no_wait)  # type: ignore[arg-type]
    await _run(poller, lambda: main.deleted and tenant.deleted)

    assert main.deleted == [{"drop_pending_updates": False}]
    assert tenant.deleted == [{"drop_pending_updates": False}]


async def test_a_resellers_updates_are_served_as_the_resellers_shop() -> None:
    main = FakeBot([[Update(update_id=10)]])
    tenant = FakeBot([[Update(update_id=20)]])
    dispatcher = FakeDispatcher()

    async def tenants() -> dict[uuid.UUID, Any]:
        return {RESELLER: tenant}

    poller = UpdatePoller(dispatcher, main_bot=main, tenants=tenants, sleep=_no_wait)  # type: ignore[arg-type]
    await _run(poller, lambda: len(dispatcher.fed) == 2)

    fed = {update_id: (bot, extra) for bot, update_id, extra in dispatcher.fed}
    assert fed[10] == (main, {})
    assert fed[20] == (tenant, {"reseller_id": RESELLER.hex, "stickers": None})


async def test_the_offset_moves_past_what_was_handled() -> None:
    main = FakeBot([[Update(update_id=41), Update(update_id=42)]])

    async def tenants() -> dict[uuid.UUID, Any]:
        return {}

    poller = UpdatePoller(FakeDispatcher(), main_bot=main, tenants=tenants, sleep=_no_wait)  # type: ignore[arg-type]
    await _run(poller, lambda: len(main.offsets) >= 2)

    assert main.offsets[:2] == [None, 43]


async def test_a_failing_proxy_is_retried_rather_than_fatal() -> None:
    main = FakeBot([ConnectionError("proxy down"), [Update(update_id=7)]])
    dispatcher = FakeDispatcher()

    async def tenants() -> dict[uuid.UUID, Any]:
        return {}

    poller = UpdatePoller(dispatcher, main_bot=main, tenants=tenants, sleep=_no_wait)  # type: ignore[arg-type]
    await _run(poller, lambda: dispatcher.fed)

    assert [update_id for _, update_id, _ in dispatcher.fed] == [7]


async def test_switching_back_to_webhooks_restores_every_resellers_webhook() -> None:
    from geekvpn.application.resellers.tenant_bots import tenant_secret
    from geekvpn.infrastructure.config.settings import Settings, TelegramSettings
    from geekvpn.presentation.bot.app import register_tenant_webhooks

    tenant = FakeBot([])

    class Tenants:
        async def active(self) -> dict[uuid.UUID, Any]:
            return {RESELLER: tenant}

    settings = Settings(
        telegram=TelegramSettings(
            webhook_base_url="https://shop.example",
            webhook_secret="s3cret",  # type: ignore[arg-type]
        )
    )
    count = await register_tenant_webhooks(Tenants(), settings, allowed_updates=["message"])  # type: ignore[arg-type]

    assert count == 1
    assert tenant.webhooks == [
        {
            "url": f"https://shop.example/telegram/webhook/r/{RESELLER.hex}",
            "secret_token": tenant_secret("s3cret", RESELLER),
            "drop_pending_updates": False,
            "allowed_updates": ["message"],
        }
    ]


def test_webhooks_stay_the_default() -> None:
    from geekvpn.infrastructure.config.settings import TelegramSettings

    assert TelegramSettings().mode == "webhook"


@pytest.mark.parametrize("mode", ["webhook", "polling"])
def test_the_mode_and_proxy_come_from_the_env_file_keys(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """The exact keys an operator writes in `.env` during an outage."""
    from geekvpn.infrastructure.config.settings import Settings

    monkeypatch.setenv("TELEGRAM__MODE", mode)
    monkeypatch.setenv("PROXY__URL", "socks5://u:p@10.0.0.9:1080")
    monkeypatch.setenv("PROXY__EXTRA_HOSTS", "github.com")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.telegram.mode == mode
    assert settings.proxy.url.get_secret_value() == "socks5://u:p@10.0.0.9:1080"
    assert settings.proxy.extra_hosts == "github.com"
