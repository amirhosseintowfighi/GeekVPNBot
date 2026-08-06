"""Where secrets come from, and how a bad one is caught at boot.

The project already refuses to start with a default secret in production (see
``config/settings.py``). This module is the layer underneath that: it decides
*where* a secret may be read from, and it exists mainly to support the file
convention.

Why files, not just environment variables
----------------------------------------
An environment variable is readable from ``/proc/<pid>/environ``, appears in
``docker inspect``, is inherited by every child process the API ever spawns, and
is dumped verbatim by most crash reporters. A file mounted at 0400 is readable
by one uid and shows up in none of those places. Docker and Kubernetes both
mount secrets as files, so the ``NAME_FILE`` convention is what the platforms
actually want - the environment variable is the compatibility path, not the
good one.

A deliberate non-feature: there is no ``get_or_default`` for secrets. A secret
with a fallback is a secret that ships to production unset, which is how
``SECRET_KEY = "changeme"`` reaches the internet.
"""

from __future__ import annotations

import os
import re
import secrets
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

#: Suffix that turns ``FOO`` into "read FOO's value from the file at FOO_FILE".
FILE_SUFFIX: Final = "_FILE"

#: Minimum length for anything used as a signing or encryption key. 32 chars is
#: the floor HMAC-SHA256 stops being trivially brute-forceable at.
MIN_KEY_LENGTH: Final = 32

#: Values that appear in every tutorial and therefore in every attacker's first
#: guess list.
WEAK_VALUES: Final = frozenset(
    {
        "",
        "123456",
        "admin",
        "changeme",
        "default",
        "geekvpn",
        "letmein",
        "password",
        "postgres",
        "redis",
        "root",
        "secret",
        "test",
        "token",
    }
)

#: Any secret containing this is a development placeholder by construction.
INSECURE_MARKERS: Final = ("insecure", "do-not-use", "example", "sample", "todo")

_LOW_ENTROPY_PATTERN: Final = re.compile(r"^(.)\1*$")
_ALPHABET: Final = string.ascii_letters + string.digits + "-_"


class SecretsError(RuntimeError):
    """A secret is missing or unusable. Always a boot-time failure."""


@runtime_checkable
class SecretsProvider(Protocol):
    def get(self, name: str) -> str | None:
        """Return the secret's value, or None when it is not configured."""
        ...


@dataclass(frozen=True, slots=True)
class EnvSecretsProvider:
    """Reads ``NAME``, falling back to the contents of the file at ``NAME_FILE``.

    The file wins when both are present: a mounted secret is a deliberate act
    by the operator, while a stray environment variable is usually inherited
    from a shell or a compose default.
    """

    environ: Mapping[str, str] | None = None

    def _env(self) -> Mapping[str, str]:
        return self.environ if self.environ is not None else os.environ

    def get(self, name: str) -> str | None:
        env = self._env()
        path = env.get(f"{name}{FILE_SUFFIX}")
        if path:
            return _read_secret_file(path)
        value = env.get(name)
        return value if value else None


@dataclass(frozen=True, slots=True)
class StaticSecretsProvider:
    """In-memory provider. For tests and for the bootstrap of a key ring."""

    values: Mapping[str, str]

    def get(self, name: str) -> str | None:
        value = self.values.get(name)
        return value if value else None


@dataclass(frozen=True, slots=True)
class ChainSecretsProvider:
    """First provider that has the secret wins."""

    providers: Sequence[SecretsProvider]

    def get(self, name: str) -> str | None:
        for provider in self.providers:
            value = provider.get(name)
            if value:
                return value
        return None


def _read_secret_file(path: str) -> str:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        # The path is safe to name: it is configuration, not a secret. The
        # contents never appear in the message.
        raise SecretsError(f"Could not read the secret file at {path!r}.") from exc
    # A trailing newline is what every ``echo secret > file`` produces and the
    # cause of a whole genre of "the password is wrong but it looks right" bugs.
    value = raw.strip()
    if not value:
        raise SecretsError(f"The secret file at {path!r} is empty.")
    return value


def weakness_of(value: str, *, min_length: int = 1) -> str | None:
    """Return a Persian-free, log-safe reason the value is unfit, or None.

    Never returns the value itself, so the reason can be logged.
    """
    if len(value) < min_length:
        return f"shorter than the {min_length}-character minimum"
    lowered = value.lower()
    if lowered in WEAK_VALUES:
        return "a well-known placeholder value"
    for marker in INSECURE_MARKERS:
        if marker in lowered:
            return f"contains the development marker {marker!r}"
    if _LOW_ENTROPY_PATTERN.match(value):
        return "a single repeated character"
    if len(set(value)) < 5 and len(value) >= MIN_KEY_LENGTH:
        # "abababab..." passes a length check and fails a real one.
        return "fewer than five distinct characters"
    return None


def require(
    provider: SecretsProvider,
    name: str,
    *,
    min_length: int = 1,
) -> str:
    """Fetch a secret or refuse to continue."""
    value = provider.get(name)
    if value is None:
        raise SecretsError(
            f"{name} is not configured. Set {name} or mount it at {name}{FILE_SUFFIX}."
        )
    reason = weakness_of(value, min_length=min_length)
    if reason is not None:
        raise SecretsError(f"{name} is unusable: {reason}.")
    return value


def require_key(provider: SecretsProvider, name: str) -> str:
    """``require`` with the key-length floor applied."""
    return require(provider, name, min_length=MIN_KEY_LENGTH)


def optional(provider: SecretsProvider, name: str) -> str | None:
    value = provider.get(name)
    if value is None:
        return None
    reason = weakness_of(value)
    if reason is not None:
        raise SecretsError(f"{name} is set but unusable: {reason}.")
    return value


def audit(
    provider: SecretsProvider, names: Sequence[str], *, keys: Sequence[str] = ()
) -> list[str]:
    """Report every problem at once instead of failing on the first.

    An operator deploying for the first time should get one list of everything
    that is wrong, not five consecutive failed boots.
    """
    problems: list[str] = []
    for name in (*names, *keys):
        minimum = MIN_KEY_LENGTH if name in set(keys) else 1
        value = provider.get(name)
        if value is None:
            problems.append(f"{name}: not configured")
            continue
        reason = weakness_of(value, min_length=minimum)
        if reason is not None:
            problems.append(f"{name}: {reason}")
    return problems


def generate_secret(length: int = 48) -> str:
    """Generate a secret for an operator to paste into a vault.

    Uses ``secrets``, never ``random``: ``random`` is a Mersenne Twister whose
    entire future output is recoverable from 624 observed outputs.
    """
    if length < MIN_KEY_LENGTH:
        raise ValueError(f"Refusing to generate a secret shorter than {MIN_KEY_LENGTH}.")
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def redact(value: str | None, *, keep: int = 4) -> str:
    """``sk_live_...c3f9`` - enough to match against a vault, not to use."""
    if not value:
        return "<unset>"
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-keep:]}"


__all__ = [
    "FILE_SUFFIX",
    "INSECURE_MARKERS",
    "MIN_KEY_LENGTH",
    "WEAK_VALUES",
    "ChainSecretsProvider",
    "EnvSecretsProvider",
    "SecretsError",
    "SecretsProvider",
    "StaticSecretsProvider",
    "audit",
    "generate_secret",
    "optional",
    "redact",
    "require",
    "require_key",
    "weakness_of",
]
