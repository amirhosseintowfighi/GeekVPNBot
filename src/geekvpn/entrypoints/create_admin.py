"""Create the first administrator.

    docker compose exec api python -m geekvpn.entrypoints.create_admin \\
        --username amir --role super_admin

The password is read from the `GEEKVPN_ADMIN_PASSWORD` environment variable or
prompted for interactively - never passed as an argument, because arguments end
up in shell history and in `ps` output.

It refuses to overwrite an existing administrator. Rotating a password is a
different, audited operation.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from geekvpn.domain.identity.permissions import AdminRole
from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.di.container import build_container, close_container
from geekvpn.infrastructure.di.scope import build_scope

PASSWORD_ENV_VAR = "GEEKVPN_ADMIN_PASSWORD"  # noqa: S105 - a variable name


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a Geek VPN administrator.")
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--role",
        default=AdminRole.SUPER_ADMIN.value,
        choices=[role.value for role in AdminRole],
    )
    parser.add_argument("--email", default=None)
    parser.add_argument("--telegram-id", type=int, default=None)
    return parser.parse_args(argv)


async def _create(args: argparse.Namespace, password: str) -> int:
    settings = get_settings()
    container = build_container(settings)
    try:
        async with container.unit_of_work() as uow:
            scope = build_scope(container, uow.session)
            if await scope.admins.get_by_username(args.username.lower()) is not None:
                sys.stderr.write(f"Administrator '{args.username}' already exists.\\n")
                return 1
            profile = await scope.manage_admins.create(
                username=args.username,
                password=password,
                role=AdminRole(args.role),
                email=args.email,
                telegram_id=args.telegram_id,
            )
            await uow.commit()
        sys.stdout.write(
            f"Created administrator '{profile.username}' "
            f"with role '{profile.role}' and id {profile.id}.\\n"
        )
        return 0
    finally:
        await close_container(container)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    password = os.environ.get(PASSWORD_ENV_VAR) or getpass.getpass("Password: ")
    if not password:
        sys.stderr.write("A password is required.\\n")
        return 2
    return asyncio.run(_create(args, password))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
