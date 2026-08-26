"""A script nobody can run is a script that is not there.

`scripts/deploy.sh` was committed 100644. It has a shebang, the README tells an
operator to run it as `./scripts/deploy.sh`, and on a fresh clone that is
`Permission denied` - in the middle of a deploy, which is exactly when nobody
wants to be reading about file modes.

The mode is checked in the git index rather than on disk: a Windows checkout
has no exec bit to inspect, and the index is what a clone on the server
actually receives.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

pytestmark = pytest.mark.integration

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _indexed_modes() -> dict[str, str]:
    out = subprocess.run(
        ["git", "ls-files", "-s"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    modes: dict[str, str] = {}
    for line in out.splitlines():
        head, _, path = line.partition("\t")
        modes[path] = head.split()[0]
    return modes


def test_every_shell_script_meant_to_be_run_is_executable():
    """Having a shebang is the declaration that this file is run, not sourced."""
    modes = _indexed_modes()
    not_executable = []
    for path, mode in modes.items():
        if not path.endswith(".sh"):
            continue
        first = (ROOT / path).read_text(encoding="utf-8", errors="ignore").split("\n", 1)[0]
        if first.startswith("#!") and mode != "100755":
            not_executable.append(path)

    assert not not_executable, f"shebang but not executable: {not_executable}"
