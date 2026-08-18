"""The installer must satisfy what Compose demands.

A fresh install failed twice in a row on this exact mismatch: Compose marks a
variable required with `${VAR:?...}`, the wizard did not write it, and the
failure only appeared partway through - after the operator had already typed
their bot token and admin password, and after `.env` had been written.

Every one of those failures was findable by reading two files side by side, so
that is what this does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

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
