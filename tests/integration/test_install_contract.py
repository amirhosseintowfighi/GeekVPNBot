"""The installer must satisfy what Compose demands - and what Settings does.

A fresh install failed twice in a row on this exact mismatch: Compose marks a
variable required with `${VAR:?...}`, the wizard did not write it, and the
failure only appeared partway through - after the operator had already typed
their bot token and admin password, and after `.env` had been written.

Every one of those failures was findable by reading two files side by side, so
that is what this does. The second half does the same against the settings
model: the wizard wrote `TELEGRAM__WEBHOOK_URL`, which is a computed field and
therefore rejected as an extra input, so `alembic upgrade` died on the
generated .env after the operator had typed everything in. Nothing in the suite
had ever fed the wizard's own output to `Settings`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from geekvpn.infrastructure.config.settings import Settings

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "scripts" / "install.sh"

#: `${VAR:?message}` - Compose refuses to start without it.
_REQUIRED = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):\?")
#: A `KEY=` at the start of a line inside the heredoc the wizard writes.
_ASSIGNED = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def compose_files() -> list[Path]:
    return sorted(ROOT.glob("docker-compose*.yml"))


def required_variables() -> set[str]:
    found: set[str] = set()
    for path in compose_files():
        found |= set(_REQUIRED.findall(path.read_text(encoding="utf-8")))
    return found


def written_variables() -> set[str]:
    """Only the block the wizard writes into .env, not the whole script."""
    text = INSTALL.read_text(encoding="utf-8")
    start = text.index('cat > "$ENV_FILE"')
    end = text.index("\nEOF", start)
    return set(_ASSIGNED.findall(text[start:end]))


def test_the_files_this_reads_actually_exist() -> None:
    assert INSTALL.is_file()
    assert compose_files()
    assert required_variables()


def test_the_wizard_writes_every_variable_compose_requires() -> None:
    missing = required_variables() - written_variables()
    assert not missing, (
        "docker compose requires these and scripts/install.sh never writes them, "
        "so a fresh install dies partway through:\n  " + "\n  ".join(sorted(missing))
    )


def test_no_required_variable_is_written_empty() -> None:
    """`${VAR:?}` rejects an empty value as well as an unset one.

    REDIS__PASSWORD was written as a bare `REDIS__PASSWORD=`, which reads as
    "present" to a human skimming .env and as "missing" to Compose.
    """
    text = INSTALL.read_text(encoding="utf-8")
    start = text.index('cat > "$ENV_FILE"')
    end = text.index("\nEOF", start)
    body = text[start:end]

    empty = {
        name
        for name in required_variables()
        if re.search(rf"^{re.escape(name)}=\s*$", body, re.MULTILINE)
    }
    assert not empty, "written with no value, which Compose treats as missing:\n  " + "\n  ".join(
        sorted(empty)
    )


def test_the_installer_is_valid_bash() -> None:
    """Guards against the CRLF class of failure too: a stray carriage return
    makes `set -Eeuo pipefail` an invalid option name."""
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover - CI has bash
        pytest.skip("bash is not available")
    # On Windows `where bash` finds the WSL launcher stub, which is not a shell
    # and answers every invocation with UTF-16 install advice.
    # Both calls run a shell this machine already has, on a path from this
    # repository. Nothing here comes from input.
    probe = subprocess.run([bash, "-c", "echo ok"], capture_output=True)  # noqa: S603
    if probe.returncode != 0 or probe.stdout.strip() != b"ok":  # pragma: no cover
        pytest.skip("the bash on PATH is not a working shell")

    checked = subprocess.run([bash, "-n", str(INSTALL)], capture_output=True)  # noqa: S603
    assert checked.returncode == 0, checked.stderr.decode(errors="replace")


@pytest.mark.parametrize(
    "script",
    [p.name for p in sorted((ROOT / "scripts").glob("*.sh"))] + ["../docker/nginx/entrypoint.sh"],
)
def test_shipped_shell_scripts_have_unix_line_endings(script: str) -> None:
    """A CR makes bash report `invalid option name`, and then overwrites the
    start of its own error message, which is why the cause is unreadable."""
    path = (ROOT / "scripts" / script).resolve()
    assert b"\r" not in path.read_bytes(), f"{script} has CRLF line endings"


def env_block() -> str:
    """The heredoc the wizard writes, verbatim."""
    text = INSTALL.read_text(encoding="utf-8")
    start = text.index('cat > "$ENV_FILE"')
    return text[text.index("\n", start) + 1 : text.index("\nEOF", start)]


#: Stand-ins for what the wizard asks the operator, and for what it generates.
#: The two key secrets differ because a production guardrail refuses to boot
#: while they match.
ANSWERS = {
    "DOMAIN": "vpn.example.ir",
    "CERTBOT_EMAIL": "ops@example.ir",
    "BOT_TOKEN": "123456:AAHtesttokenfortestingonly",
    "MINIAPP_ORIGIN": "https://app.example.ir",
    "ALERT_CHAT": "-1001234567890",
    "SECRET_KEY": "S" * 48,
    "ENCRYPTION_KEY": "E" * 48,
    "WEBHOOK_SECRET": "W" * 48,
    "PG_PASSWORD": "P" * 48,
    "REDIS_PASSWORD": "R" * 48,
    "GRAFANA_PASSWORD": "G" * 48,
}


def rendered_env(admin_ips: str) -> str:
    body = re.sub(r"\$\((?:[^()]|\([^()]*\))*\)", "generated-at-install-time", env_block())
    body = body.replace("${ADMIN_IPS}", admin_ips)
    for name, value in ANSWERS.items():
        body = body.replace("${" + name + "}", value)
    leftover = re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", body)
    assert not leftover, (
        "the wizard interpolates shell variables this test does not know about, "
        f"so it is no longer rendering what ships: {sorted(set(leftover))}"
    )
    return body


@pytest.mark.parametrize(
    ("case", "admin_ips"),
    [("no allowlist", ""), ("a CIDR allowlist", "10.0.0.0/24,203.0.113.9")],
)
def test_the_generated_env_file_boots_the_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, admin_ips: str
) -> None:
    """`APP__ENV=production`, so this asserts the wizard's output satisfies
    every production guardrail as well as the field definitions."""
    for name in list(os.environ):
        # The ambient test environment must not stand in for a line the wizard
        # forgot to write, nor mask one it wrote wrongly.
        if "__" in name:
            monkeypatch.delenv(name, raising=False)
    written = tmp_path / ".env"
    written.write_text(rendered_env(admin_ips), encoding="utf-8")

    settings = Settings(_env_file=written)  # type: ignore[call-arg]

    assert settings.telegram.webhook_url == "https://vpn.example.ir/telegram/webhook"
    assert settings.security.cors_origins == ("https://app.example.ir",)
    assert settings.jwt_secret == "S" * 48


def test_the_generated_env_file_configures_the_admin_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The answer is typed comma-separated at the prompt and has to survive
    both the .env round trip and CIDR parsing."""
    from geekvpn.infrastructure.security.ip_allowlist import IpAllowlist

    for name in list(os.environ):
        if "__" in name:
            monkeypatch.delenv(name, raising=False)
    written = tmp_path / ".env"
    written.write_text(rendered_env("10.0.0.0/24,203.0.113.9"), encoding="utf-8")

    settings = Settings(_env_file=written)  # type: ignore[call-arg]
    allowlist = IpAllowlist.from_entries(settings.auth.admin_ip_allowlist)

    assert allowlist.allows("10.0.0.77")
    assert not allowlist.allows("198.51.100.4")
