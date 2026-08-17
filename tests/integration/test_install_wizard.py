"""The install wizard must agree with the code it installs.

A wizard is the one script nobody runs during development, so its mistakes are
found by an operator on a fresh server with no way to debug them. Every
assertion here pins a name the wizard hardcodes against the thing that actually
reads it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
WIZARD = ROOT / "scripts" / "install.sh"


@pytest.fixture(scope="module")
def script() -> str:
    return WIZARD.read_text(encoding="utf-8")


def test_the_wizard_exists_and_is_a_bash_script(script: str) -> None:
    assert script.startswith("#!/usr/bin/env bash")


def test_it_uses_the_password_variable_create_admin_actually_reads(script: str) -> None:
    """create_admin falls back to getpass, which has no terminal inside
    `compose run` - the wrong name here hangs the install with no output."""
    from geekvpn.entrypoints.create_admin import PASSWORD_ENV_VAR

    assert PASSWORD_ENV_VAR in script


def test_it_writes_the_environment_key_the_settings_actually_declare(script: str) -> None:
    """`.env.example` once carried APP__ENVIRONMENT, which does not exist and
    fails the boot with an error naming a field nobody can grep for."""
    assert re.search(r"^APP__ENV=", script, re.MULTILINE)
    assert not re.search(r"^APP__ENVIRONMENT=", script, re.MULTILINE)


@pytest.mark.parametrize(
    "variable",
    [
        "SECURITY__SECRET_KEY",
        "SECURITY__ENCRYPTION_MASTER_KEY",
        "TELEGRAM__BOT_TOKEN",
        "TELEGRAM__WEBHOOK_SECRET",
        "POSTGRES__PASSWORD",
    ],
)
def test_every_variable_the_production_guardrail_demands_is_written(
    script: str, variable: str
) -> None:
    """The guardrail refuses to boot without these, and names them one at a
    time - an operator would otherwise discover them across five restarts."""
    assert re.search(rf"^{re.escape(variable)}=", script, re.MULTILINE)


def test_it_does_not_set_a_bootstrap_admin_password(script: str) -> None:
    """The same guardrail refuses to boot *while* one is set, and the wizard
    creates the administrator directly instead."""
    assert not re.search(r"^AUTH__BOOTSTRAP_ADMIN_PASSWORD=.+", script, re.MULTILINE)


def test_the_two_master_keys_are_generated_separately(script: str) -> None:
    """Sharing one secret couples JWT rotation to re-encrypting every stored
    card number, so the guardrail refuses to boot when they match."""
    assert script.count("$(gen_secret)") >= 3
    assert '"$SECRET_KEY" != "$ENCRYPTION_KEY"' in script


def test_generated_secrets_avoid_the_markers_the_weakness_check_rejects(
    script: str,
) -> None:
    """`weakness_of` refuses any value containing a development marker, so a
    generator that ignored them would occasionally produce a key that this
    platform then rejects at boot."""
    from geekvpn.infrastructure.security.secrets_provider import INSECURE_MARKERS

    guard = re.search(r"grep -qiE '([^']+)'", script)
    assert guard is not None
    pattern = guard.group(1)
    for marker in INSECURE_MARKERS:
        assert marker in pattern, marker


def test_it_refuses_a_database_that_already_has_tables(script: str) -> None:
    """This is an installer, not an upgrade path. Running it over live data
    would be the single most destructive thing in the repository."""
    assert "information_schema.tables" in script
    assert "only installs onto an empty database" in script


def test_it_creates_the_schema_through_alembic(script: str) -> None:
    """A fresh install still goes through Alembic. create_all would produce the
    same tables and leave no version stamp, breaking every future upgrade."""
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert "alembic upgrade head" in code
    assert "create_all" not in code


def test_it_does_not_overwrite_an_existing_env_without_asking(script: str) -> None:
    assert ".env.backup" in script
    assert 'if [[ -f "$ENV_FILE" ]]' in script


def test_the_env_file_is_written_with_restrictive_permissions(script: str) -> None:
    """It holds the encryption master key."""
    assert 'chmod 600 "$ENV_FILE"' in script
    assert "umask 077" in script
