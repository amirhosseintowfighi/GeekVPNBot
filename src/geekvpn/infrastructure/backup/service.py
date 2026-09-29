"""Taking a backup and sending it where the operator asked.

Used by the worker on a schedule and by the operator's "back up now" button,
so both produce the same file with the same caption.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from geekvpn.application.platform.settings_service import BACKUP_CHAT, BACKUP_INTERVAL_HOURS
from geekvpn.domain.analytics.calendar import to_jalali
from geekvpn.infrastructure.backup.archive import BackupSummary, export_archive
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.infrastructure.notifications.telegram import HttpOperatorSender
from geekvpn.infrastructure.persistence.repositories.sync_settings import SyncSettings

logger = get_logger("backup")

#: The Bot API refuses uploads over 50 MB. Checked before sending so the
#: operator is told why no file arrived, instead of nothing arriving.
TELEGRAM_UPLOAD_LIMIT = 50 * 1024 * 1024

#: When the last scheduled backup went out, in the shared cache.
LAST_RUN_KEY = "backup:last_run"

CAPTION_FA = (
    "🗄 <b>بکاپ دیتابیس</b>\n"
    "تاریخ: {date}\n"
    "رکوردها: {rows}\n"
    "نسخهٔ اسکیما: <code>{revision}</code>\n\n"
    "برای بازگردانی: <code>python -m geekvpn.entrypoints.backup restore FILE</code>"
)
TOO_LARGE_FA = "⚠️ بکاپ دیتابیس {size} مگابایته و از سقف ۵۰ مگابایتی تلگرام بزرگ‌تره؛ ارسال نشد."


@dataclass(frozen=True, slots=True)
class BackupSettings:
    chat_id: int
    interval_hours: int


def backup_settings(container: Container) -> BackupSettings:
    with container.sync_sessions() as session:
        settings = SyncSettings(session)
        return BackupSettings(
            chat_id=settings.get(BACKUP_CHAT),
            interval_hours=settings.get(BACKUP_INTERVAL_HOURS),
        )


def send_backup(container: Container, chat_id: int) -> BackupSummary:
    """Export, upload, delete the local copy. Blocking; run it off the loop."""
    now = container.clock.now()
    year, month, day = to_jalali(now.date())
    name = f"geekvpn-{year:04d}{month:02d}{day:02d}-{now:%H%M}.zip"
    sender = HttpOperatorSender(container.settings.telegram.bot_token.get_secret_value())
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / name
        summary = export_archive(container.sync_engine, path, created_at=now)
        if summary.size_bytes > TELEGRAM_UPLOAD_LIMIT:
            sender.send_text(
                chat_id=chat_id,
                text=TOO_LARGE_FA.format(size=summary.size_bytes // (1024 * 1024)),
                buttons=(),
            )
            return summary
        sender.send_document(
            chat_id=chat_id,
            path=path,
            caption=CAPTION_FA.format(
                date=f"{year}/{month:02d}/{day:02d} {now:%H:%M}",
                rows=summary.total_rows,
                revision=summary.revision,
            ),
        )
    logger.info("backup.sent", chat_id=chat_id, rows=summary.total_rows, bytes=summary.size_bytes)
    return summary


def is_due(last_run: datetime | None, *, now: datetime, interval_hours: int) -> bool:
    if last_run is None:
        return True
    return (now - last_run).total_seconds() >= interval_hours * 3600


__all__ = ["LAST_RUN_KEY", "BackupSettings", "backup_settings", "is_due", "send_backup"]
