"""Create the first administrator, and enrol the second factor it needs.

    docker compose exec api python -m geekvpn.entrypoints.create_admin \\
        --username amir --role super_admin

The password is read from the `GEEKVPN_ADMIN_PASSWORD` environment variable or
prompted for interactively - never passed as an argument, because arguments end
up in shell history and in `ps` output.

It refuses to overwrite an existing administrator. Rotating a password is a
different, audited operation.

A super admin always requires 2FA - `Admin.requires_totp` is true for the role
whether or not a secret exists - so creating one and walking away left an
account that demanded a code nobody could produce. The secret is printed once,
here, and never again: it is stored encrypted and every later read verifies a
code rather than revealing the key.

    ... create_admin --username amir --reset-totp

re-enrols an administrator who has lost their authenticator, which is also the
way out for an account created before this enrolled anything.

    ... create_admin --username amir --link-telegram 123456789

attaches the Telegram account the administrator acts through. Approving a
payment, refunding one, adjusting a wallet, answering a ticket and sending a
broadcast all record that id and all refuse without it, so an administrator
created without one can sign in and then do none of the work.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from geekvpn.application.identity.dto import TotpEnrolment
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
    parser.add_argument(
        "--reset-totp",
        action="store_true",
        help="Issue a new second factor for an existing administrator and exit.",
    )
    parser.add_argument(
        "--link-telegram",
        type=int,
        default=None,
        metavar="TELEGRAM_ID",
        help="Attach a Telegram account to an existing administrator and exit.",
    )
    return parser.parse_args(argv)


def _report_enrolment(enrolment: TotpEnrolment) -> None:
    """Print the secret in the two forms an authenticator can take it.

    Both, not one: a phone scans the URI as a QR code, and a password manager
    on the same machine as this terminal takes the secret by paste.
    """
    sys.stdout.write(
        "\n"
        "Two-factor enrolment for "
        f"'{enrolment.username}' - this is shown once and cannot be recovered:\n"
        "\n"
        f"  secret  {enrolment.secret}\n"
        f"  uri     {enrolment.provisioning_uri}\n"
        "\n"
        "Add it to an authenticator app now. Sign-in asks for a code from it,\n"
        "and a super admin cannot sign in without one.\n"
    )


async def _reset_totp(username: str) -> int:
    settings = get_settings()
    container = build_container(settings)
    try:
        async with container.unit_of_work() as uow:
            scope = build_scope(container, uow.session)
            if await scope.admins.get_by_username(username.lower()) is None:
                sys.stderr.write(f"No administrator named '{username}'.\n")
                return 1
            enrolment = await scope.manage_admins.enrol_totp(username=username)
            await uow.commit()
        _report_enrolment(enrolment)
        return 0
    finally:
        await close_container(container)


async def _link_telegram(username: str, telegram_id: int) -> int:
    settings = get_settings()
    container = build_container(settings)
    try:
        async with container.unit_of_work() as uow:
            scope = build_scope(container, uow.session)
            if await scope.admins.get_by_username(username.lower()) is None:
                sys.stderr.write(f"No administrator named '{username}'.\n")
                return 1
            await scope.manage_admins.link_telegram(username=username, telegram_id=telegram_id)
            await uow.commit()
        sys.stdout.write(
            f"Administrator '{username}' now acts as Telegram id {telegram_id}.\n"
            "Approving payments, refunding, adjusting wallets, answering tickets and\n"
            "sending broadcasts all record that id, and all refuse without it.\n"
        )
        return 0
    finally:
        await close_container(container)


async def _create(args: argparse.Namespace, password: str) -> int:
    settings = get_settings()
    container = build_container(settings)
    role = AdminRole(args.role)
    try:
        async with container.unit_of_work() as uow:
            scope = build_scope(container, uow.session)
            if await scope.admins.get_by_username(args.username.lower()) is not None:
                sys.stderr.write(f"Administrator '{args.username}' already exists.\n")
                return 1
            profile = await scope.manage_admins.create(
                username=args.username,
                password=password,
                role=role,
                email=args.email,
                telegram_id=args.telegram_id,
            )
            # Only for the role that cannot sign in without it. For everyone
            # else 2FA stays opt-in, and enrolling here would force it on an
            # operator who never asked for it.
            enrolment = (
                await scope.manage_admins.enrol_totp(username=profile.username)
                if role is AdminRole.SUPER_ADMIN
                else None
            )
            await uow.commit()
        sys.stdout.write(
            f"Created administrator '{profile.username}' "
            f"with role '{profile.role}' and id {profile.id}.\n"
        )
        if enrolment is not None:
            _report_enrolment(enrolment)
        return 0
    finally:
        await close_container(container)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.link_telegram is not None:
        return asyncio.run(_link_telegram(args.username, args.link_telegram))
    if args.reset_totp:
        # No password: this proves nothing that shell access to the container
        # does not already prove, and demanding one would lock out the operator
        # who forgot it as thoroughly as the missing secret already has.
        return asyncio.run(_reset_totp(args.username))
    password = os.environ.get(PASSWORD_ENV_VAR) or getpass.getpass("Password: ")
    if not password:
        sys.stderr.write("A password is required.\n")
        return 2
    return asyncio.run(_create(args, password))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
