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
from fnmatch import fnmatch
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


def test_no_compose_command_runs_before_env_is_written() -> None:
    """Compose interpolates the file on every invocation, `down` included, and
    `${POSTGRES__PASSWORD:?...}` makes that a hard error when .env is absent.

    The stale-volume guard was written with `$COMPOSE down -v` and sat before
    the wizard writes .env, so it failed on exactly the fresh checkout it
    exists to rescue - and its `|| true` swallowed the failure, leaving the
    volume in place and the install to die later on a password mismatch.
    """
    text = INSTALL.read_text(encoding="utf-8")
    writes_env = text.index('cat > "$ENV_FILE"')

    # Line starts only: `$COMPOSE` also appears inside prose, including the
    # comment explaining why the guard below must not use it.
    early = [
        line.strip()
        for line in text[:writes_env].splitlines()
        if line.lstrip().startswith("$COMPOSE")
    ]

    assert not early, (
        "these run before .env exists, and every compose invocation "
        "interpolates it:\n  " + "\n  ".join(early)
    )


def test_the_image_is_built_before_anything_runs_from_it() -> None:
    """docker-compose.prod.yml pins the backend services to an image tag, and
    Compose builds implicitly only when that tag is absent. So the first run
    built the image and every later run reused it, source and migrations
    frozen at whatever the first run checked out - which made a fix pulled
    from git look like it had not been applied.

    This is a claim about the order of two lines in a shell script, so
    checking the text of the script is checking the thing itself. It is not a
    substitute for running the installer, which needs a Docker daemon.
    """
    text = INSTALL.read_text(encoding="utf-8")

    build = text.find("$COMPOSE build")
    assert build != -1, "install.sh never builds the image it then runs migrations from"

    for consumer in ("$COMPOSE run --rm migrate", "$COMPOSE up -d postgres redis"):
        assert text.find(consumer) > build, f"{consumer} runs before the image is built"


#: Bind mounts that are meant to be created empty at run time. Docker making a
#: directory here is the intended behaviour, not the bug below.
RUNTIME_DIRECTORIES: frozenset[str] = frozenset({"./backups", "./backups/metrics"})


def test_every_bind_mount_source_exists_in_the_repository() -> None:
    """Docker creates a *directory* at a bind mount's host path when that path
    does not exist. So a compose file naming a file this repository does not
    ship does not fail: it silently produces a directory where the file should
    be, in the working tree, permanently. On this server that turned
    `docker/nginx/conf.d/active-api.conf` into a directory and every later
    deploy died on `grep: ...: Is a directory`.
    """
    sources = set()
    for path in compose_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"\s*-\s+(\./[^:\s]+):", line)
            if match:
                sources.add(match.group(1))

    assert sources, "no bind mounts found; this test is no longer reading the compose files"

    missing = sorted(
        source
        for source in sources
        if source not in RUNTIME_DIRECTORIES and not (ROOT / source).exists()
    )
    assert not missing, (
        "these are bind-mounted but do not exist here, so Docker will create a "
        "directory in their place:\n  " + "\n  ".join(missing)
    )


#: Hosts nginx proxies to that this stack does not run. Both front-ends exist
#: as source trees but have no compose service, so those two routes answer 502
#: until they get one. Listed rather than silently tolerated: an entry here is
#: a known gap, and anything not here is a typo.
UNPROVISIONED_BACKENDS: frozenset[str] = frozenset({"admin", "miniapp"})

NGINX_DIR = ROOT / "docker" / "nginx"


def compose_services() -> set[str]:
    """Service names, read from the base file's top-level `services:` block."""
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    block = text[text.index("\nservices:") :]
    return set(re.findall(r"^  ([a-z][a-z0-9_]*):$", block, re.MULTILINE))


def test_nginx_only_proxies_to_hosts_this_stack_runs() -> None:
    """A hostname nginx cannot resolve is not a bad route, it is a dead edge.

    Nginx resolves the host in an `upstream` block when it loads the config and
    refuses to start if any one of them is unknown, so `admin` and `miniapp` -
    which are not services anywhere in this stack - made the config unloadable
    on every host, and blue/green guaranteed one of api_blue/api_green was
    stopped and therefore unresolvable too. The targets are variables now, so
    resolution happens per request, but a name still has to be one we actually
    run or it is a 502 nobody meant to ship.
    """
    hosts: dict[str, str] = {}
    for path in sorted(NGINX_DIR.rglob("*.conf")):
        text = path.read_text(encoding="utf-8")
        for host in re.findall(r"^\s*server\s+([a-z][a-z0-9_-]*):\d+", text, re.MULTILINE):
            hosts[host] = path.name
        for host in re.findall(r"^\s*set\s+\$\w+\s+([a-z][a-z0-9_-]*):\d+;", text, re.MULTILINE):
            hosts[host] = path.name

    assert hosts, "no proxy targets found; this test has stopped reading the nginx config"

    known = compose_services() | {"api_blue", "api_green"} | UNPROVISIONED_BACKENDS
    unknown = {host: source for host, source in hosts.items() if host not in known}

    assert not unknown, "nginx proxies to hosts no compose service provides:\n  " + "\n  ".join(
        f"{host} (in {source})" for host, source in sorted(unknown.items())
    )


def test_no_nginx_upstream_block_names_a_host_that_can_be_stopped() -> None:
    """The load-time resolution half of the same bug.

    Variables defer resolution; an `upstream` block does not. Re-introducing
    one for a blue/green colour, or for a front-end that may not be deployed,
    brings back an edge that refuses to start because something it was not
    being asked to serve is absent.
    """
    fragile = sorted(UNPROVISIONED_BACKENDS | {"api_blue", "api_green"})
    for path in sorted(NGINX_DIR.rglob("*.conf")):
        text = path.read_text(encoding="utf-8")
        for host in fragile:
            assert not re.search(rf"^\s*server\s+{re.escape(host)}:\d+", text, re.MULTILINE), (
                f"{path.name} declares an upstream for {host}, which is not always running; "
                "nginx resolves that at config load and will refuse to start without it"
            )


#: conf.d files the template includes itself, inside a server or location
#: block. They must never also be pulled in at http level.
NGINX_FRAGMENTS: frozenset[str] = frozenset({"active-api.conf", "admin-allow.conf"})


def test_nginx_does_not_include_server_scoped_fragments_at_http_level() -> None:
    """`include /etc/nginx/conf.d/*.conf;` matched both fragments.

    active-api.conf holds a `set`, which is not allowed in http context, so
    nginx refused to start - and that only surfaced after the upstream blocks
    that used to fail earlier in the same parse were removed. admin-allow.conf
    is worse: `allow`/`deny` *are* valid at http level, so once
    ADMIN_ALLOW_CIDRS was configured its `deny all` would have applied to every
    server block and locked the whole edge to the admin networks, quietly.
    """
    includes = re.findall(
        r"^\s*include\s+(\S+);",
        (NGINX_DIR / "nginx.conf").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert includes, "nginx.conf includes nothing; this test has stopped reading it"

    for fragment in sorted(NGINX_FRAGMENTS):
        assert (NGINX_DIR / "conf.d" / fragment).is_file(), f"{fragment} is no longer there"
        for pattern in includes:
            assert not fnmatch(f"/etc/nginx/conf.d/{fragment}", pattern), (
                f"nginx.conf's `include {pattern};` pulls in {fragment} at http level, "
                "where it belongs to a server or location block"
            )


def plain_http_server_block() -> str:
    """The port-80 server block from the nginx template."""
    text = (NGINX_DIR / "templates" / "geekvpn.conf").read_text(encoding="utf-8")
    blocks = [f"server {{{part}" for part in text.split("\nserver {")[1:]]
    listening = [block for block in blocks if re.search(r"^\s*listen\s+80;", block, re.MULTILINE)]
    assert len(listening) == 1, f"expected exactly one port-80 server block, found {len(listening)}"
    return listening[0]


def test_scripts_only_ask_the_edge_for_paths_it_answers_directly() -> None:
    """The deploy verified itself against a URL nginx is configured to redirect.

    `wget http://localhost/health/ready` carries a Host of `localhost`, which
    matches no server_name, so it fell through to the catch-all `location /`
    and came back a 301 to HTTPS - where a fresh install has only the
    self-signed bootstrap certificate. The check could not pass, so every first
    install "failed to verify" and rolled itself back to a colour that had
    never been started.

    Anything these scripts request over plain HTTP has to be an exact location
    in that server block, which is the only way it is answered rather than
    redirected.
    """
    block = plain_http_server_block()
    answered = set(re.findall(r"^\s*location\s+=\s+(/\S*)\s*\{", block, re.MULTILINE))
    assert answered, "the port-80 server block answers nothing directly"

    for script in (INSTALL, ROOT / "scripts" / "deploy.sh"):
        text = script.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            for path in re.findall(r"http://(?:127\.0\.0\.1|localhost)(/\S*?)['\"\s]", line):
                assert path in answered, (
                    f"{script.name} asks the edge for {path}, which the port-80 server block "
                    f"does not answer directly - it redirects to HTTPS. Answered: {sorted(answered)}"
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
