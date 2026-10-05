"""Per-device connection tutorials: written by the operator, read by customers."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from geekvpn.application.platform.settings_service import TUTORIALS
from geekvpn.domain.base.errors import ValidationError
from geekvpn.domain.identity.permissions import Permission
from geekvpn.presentation.bot.handlers import admin_texts, tutorials
from geekvpn.presentation.bot.ui.callbacks import GuideCB
from tests.unit.bot.test_app_password_handler import _State

pytestmark = pytest.mark.unit


class Settings:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    async def get(self, definition: Any) -> Any:
        return self.value

    async def set(self, key: str, value: Any, **_: Any) -> None:
        self.value = value


class Chat:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Any]] = []

    async def answer_photo(self, file_id: str, **_: Any) -> None:
        self.sent.append(("photo", file_id))

    async def answer_video(self, file_id: str, **_: Any) -> None:
        self.sent.append(("video", file_id))

    async def answer(self, text: str, **_: Any) -> None:
        self.sent.append(("text", text))


def test_only_known_devices_and_kinds_are_stored() -> None:
    with pytest.raises(ValidationError):
        TUTORIALS.coerce({"nokia": {"kind": "text"}})
    with pytest.raises(ValidationError):
        TUTORIALS.coerce({"ios": {"kind": "audio"}})


def test_the_picker_offers_only_devices_that_have_a_tutorial() -> None:
    markup = tutorials._picker({"ios": {"kind": "text", "text": "x"}})

    data = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert GuideCB(device="ios").pack() in data
    assert GuideCB(device="android").pack() not in data


async def test_a_photo_tutorial_is_sent_back_as_a_photo(monkeypatch: pytest.MonkeyPatch) -> None:
    chat = Chat()
    monkeypatch.setattr(tutorials, "Message", Chat)
    query = SimpleNamespace(message=chat, answer=lambda *a, **k: _noop())
    scope = SimpleNamespace(
        settings_service=Settings({"android": {"kind": "photo", "file_id": "F1", "text": "مرحله ۱"}})
    )

    await tutorials.on_device(query, GuideCB(device="android"), scope=scope)  # type: ignore[arg-type]

    assert chat.sent == [("photo", "F1")]


async def _noop() -> None:
    return None


class Sent:
    """A message the operator sent: a photo with a caption."""

    def __init__(self) -> None:
        self.photo = [SimpleNamespace(file_id="small"), SimpleNamespace(file_id="large")]
        self.video = None
        self.text = None
        self.caption = "اول برنامه رو نصب کن"
        self.replies: list[str] = []

    async def answer(self, text: str, **_: Any) -> None:
        self.replies.append(text)


async def test_the_operators_photo_is_stored_at_its_largest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = SimpleNamespace(
        id=uuid.uuid4(),
        username="boss",
        has_permission=lambda p: p is Permission.SETTINGS_WRITE,
    )

    async def guard(scope: Any, user: Any) -> Any:
        return admin

    async def commit() -> None:
        return None

    monkeypatch.setattr(admin_texts, "_guard", guard)
    scope = SimpleNamespace(settings_service=Settings({}), session=SimpleNamespace(commit=commit))
    state = _State()
    await state.update_data(tutorial_device="ios")

    await admin_texts.on_tutorial_sent(Sent(), state, scope=scope, user=object())  # type: ignore[arg-type]

    assert scope.settings_service.value == {
        "ios": {"kind": "photo", "file_id": "large", "text": "اول برنامه رو نصب کن"}
    }
