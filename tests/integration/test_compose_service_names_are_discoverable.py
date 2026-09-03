"""A bare `docker compose` in the project directory sees the deployed stack.

The worker, the two API colours, both front-ends and certbot are defined only in
`docker-compose.prod.yml`. Compose resolves service names from the files it was
given, so `docker compose logs worker` on a server answered "no such service:
worker" - which reads exactly like the worker has died, when in fact the wrong
file was loaded. It cost a round trip of debugging a service that was running.

`COMPOSE_FILE` in the generated `.env` is what fixes it: compose reads that
variable, so every bare command targets the real composition. `deploy.sh` and
the Makefile pass `-f` explicitly and are unaffected either way.
"""

from __future__ import annotations

import pathlib
import re

import pytest

pytestmark = pytest.mark.integration

ROOT = pathlib.Path(".")
BASE = ROOT / "docker-compose.yml"
PROD = ROOT / "docker-compose.prod.yml"
INSTALL = ROOT / "scripts" / "install.sh"

#: Services an operator names when something looks wrong, and which live only
#: in the production file.
PRODUCTION_ONLY = ("worker", "api_blue", "api_green", "admin", "miniapp", "certbot")


def _services(path: pathlib.Path) -> set[str]:
    """Top-level service names, read without a YAML parser.

    Deliberately textual: the anchors at the top of these files are not valid
    service definitions, and a real parse would either choke on them or need
    configuring to ignore them.
    """
    inside = False
    found: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if re.match(r"^services:\s*$", line):
            inside = True
            continue
        if inside and re.match(r"^\S", line):
            break
        if inside:
            match = re.match(r"^  ([a-z][a-z0-9_-]*):\s*$", line)
            if match:
                found.add(match.group(1))
    return found


def test_the_worker_is_part_of_the_production_stack():
    """If this ever fails, no scheduled job runs at all: no usage sync, no
    expiry, no reminders, no broadcasts."""
    assert "worker" in _services(PROD)


def test_the_install_wizard_writes_the_compose_file_list():
    """Without it every bare compose command on the server is aimed at a
    smaller stack than the one running."""
    text = INSTALL.read_text(encoding="utf-8")

    assert "COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml" in text


def test_the_file_list_names_files_that_exist():
    """A typo here is worse than the bug it fixes: compose then refuses every
    command in the directory rather than just the ones naming a prod service."""
    text = INSTALL.read_text(encoding="utf-8")
    line = next(li for li in text.splitlines() if li.startswith("COMPOSE_FILE="))

    for name in line.split("=", 1)[1].split(":"):
        assert (ROOT / name).is_file(), name


def test_the_services_an_operator_reaches_for_are_covered():
    """Every one of these is a name somebody types while something is wrong."""
    combined = _services(BASE) | _services(PROD)

    missing = [name for name in PRODUCTION_ONLY if name not in combined]

    assert not missing, missing


def test_the_example_env_mentions_it_without_turning_it_on():
    """Local development uses the dev files; a template that switched everybody
    to the production composition would be a worse trap than the first one."""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "COMPOSE_FILE=" in text
    assert "# COMPOSE_FILE=" in text
