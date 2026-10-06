"""Approving a receipt from the receipt itself.

The receipt alert is a photo. `safe_edit` only ever called `edit_text`, which
Telegram refuses on a message without text - so approving from the alert
approved the payment and then failed, and the operator was shown an error
for something that had worked.
"""

from __future__ import annotations

from typing import Any

import pytest
from aiogram.types import Message

from geekvpn.presentation.bot.handlers.common import safe_edit

pytestmark = pytest.mark.unit


class Query:
    def __init__(self, message: Any) -> None:
        self.message = message


def message(*, photo: bool) -> Any:
    edits: list[str] = []
    payload: dict[str, Any] = {
        "message_id": 1,
        "date": 0,
        "chat": {"id": 1, "type": "private"},
    }
    if photo:
        payload["photo"] = [{"file_id": "f", "file_unique_id": "u", "width": 1, "height": 1}]
        payload["caption"] = "receipt"
    else:
        payload["text"] = "screen"
    msg = Message.model_validate(payload)

    async def edit_text(text: str, **_: Any) -> None:
        edits.append(f"text:{text}")

    async def edit_caption(caption: str, **_: Any) -> None:
        edits.append(f"caption:{caption}")

    object.__setattr__(msg, "edit_text", edit_text)
    object.__setattr__(msg, "edit_caption", edit_caption)
    return msg, edits


async def test_a_photo_has_its_caption_edited() -> None:
    msg, edits = message(photo=True)

    await safe_edit(Query(msg), "approved")  # type: ignore[arg-type]

    assert edits == ["caption:approved"]


async def test_a_text_message_still_has_its_text_edited() -> None:
    msg, edits = message(photo=False)

    await safe_edit(Query(msg), "approved")  # type: ignore[arg-type]

    assert edits == ["text:approved"]
