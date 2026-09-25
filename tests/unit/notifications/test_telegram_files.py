"""The app's receipt photo, put into Telegram and read back for its fingerprint."""

from __future__ import annotations

import httpx
import pytest

from geekvpn.infrastructure.notifications.telegram import HttpTelegramFiles, TelegramApiError

TOKEN = "123:abc"


def _response(url: str, **body: object) -> httpx.Response:
    return httpx.Response(200, json=body, request=httpx.Request("POST", url))


def test_the_photo_goes_to_the_customers_chat_and_its_largest_size_is_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        sent["url"] = url
        sent.update(kwargs)
        sizes = [{"file_id": "small"}, {"file_id": "large"}]
        return _response(url, ok=True, result={"photo": sizes})

    monkeypatch.setattr(httpx, "post", fake_post)

    file_id = HttpTelegramFiles(TOKEN).send_photo(
        chat_id=555, image=b"\xff\xd8jpeg", content_type="image/jpeg", caption="رسید"
    )

    assert file_id == "large"
    assert sent["url"] == f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    assert sent["data"] == {"chat_id": "555", "caption": "رسید"}
    assert sent["files"] == {"photo": ("receipt", b"\xff\xd8jpeg", "image/jpeg")}


def test_a_refusal_carries_telegrams_description(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            400,
            json={"ok": False, "description": "Bad Request: chat not found"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(TelegramApiError, match="chat not found"):
        HttpTelegramFiles(TOKEN).send_photo(
            chat_id=1, image=b"x", content_type="image/png", caption=""
        )


def test_download_follows_the_file_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        if url.endswith("/getFile"):
            assert kwargs["params"] == {"file_id": "large"}
            return _response(url, ok=True, result={"file_path": "photos/file_7.jpg"})
        assert url == f"https://api.telegram.org/file/bot{TOKEN}/photos/file_7.jpg"
        return httpx.Response(200, content=b"bytes", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)

    assert HttpTelegramFiles(TOKEN).download("large") == b"bytes"
