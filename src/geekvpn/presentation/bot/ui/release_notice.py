"""What customers are sent when a new version of a Geek app is published."""

from __future__ import annotations

from html import escape
from typing import Final

from geekvpn.infrastructure.client_downloads import ANDROID, ClientDownload

APP_NAMES: Final = {ANDROID: "گیک برای اندروید", "windows": "گیک برای ویندوز"}

RELEASE_TITLE: Final = "🆕 نسخهٔ جدید {app}"
RELEASE_BODY: Final = (
    "نسخهٔ <b>{version}</b> از {app} منتشر شد.\n\n"
    "برای بهترین سرعت و پایداری، همین حالا به‌روزرسانی کن:\n"
    '📥 <a href="{url}">دانلود نسخهٔ جدید</a>\n\n'
    "اگه برنامه رو نصب داری، خودش هم پیشنهاد به‌روزرسانی رو نشونت می‌ده."
)


def render_release_notice(download: ClientDownload) -> tuple[str, str]:
    """(title, body) of the broadcast. The URL is escaped: it sits in an attribute."""
    app = APP_NAMES.get(download.platform, download.platform)
    return (
        RELEASE_TITLE.format(app=app),
        RELEASE_BODY.format(
            app=app, version=escape(download.version or ""), url=escape(download.url, quote=True)
        ),
    )
