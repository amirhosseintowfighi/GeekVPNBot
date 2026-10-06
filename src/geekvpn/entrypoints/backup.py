"""Command-line backup and restore.

    python -m geekvpn.entrypoints.backup export backup.zip
    python -m geekvpn.entrypoints.backup restore backup.zip

Restoring from a file the bot sent is deliberately a command and not a bot
button: it replaces every row in the database, and the person running it
should be at the server, with the application stopped, not tapping a phone.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from geekvpn.infrastructure.backup.archive import BackupError, export_archive, restore_archive
from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.di.container import build_container


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="geekvpn-backup")
    parser.add_argument("action", choices=("export", "restore"))
    parser.add_argument("file", type=Path)
    parser.add_argument(
        "--yes", action="store_true", help="restore without asking for confirmation"
    )
    args = parser.parse_args(argv)

    container = build_container(get_settings())
    engine = container.sync_engine
    if args.action == "export":
        summary = export_archive(engine, args.file, created_at=container.clock.now())
        sys.stdout.write(
            f"{summary.total_rows} rows, {summary.size_bytes} bytes -> {summary.path}\n"
        )
        return 0

    if not args.yes:
        answer = input("This replaces EVERY row in the database. Type 'restore' to continue: ")
        if answer.strip() != "restore":
            sys.stdout.write("Cancelled.\n")
            return 1
    try:
        loaded = restore_archive(engine, args.file)
    except BackupError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    sys.stdout.write(f"Restored {sum(loaded.values())} rows into {len(loaded)} tables.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
