"""A rejected code that was valid at another time says so in the log.

A correct code, read off a phone whose clock agrees with the world, fails when
*our* clock does not. The operator is told the code is wrong, so they read a
fresh one, and that fails too, and nothing anywhere suggests the codes were
never the problem. That is being locked out of your own panel with a misleading
reason.

The acceptance window is not widened by any of this. Each accepted step
multiplies an attacker's chance at a six-digit code; the wider search happens
only after a refusal, and accepts nothing.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from geekvpn.infrastructure.security import totp as totp_module
from geekvpn.infrastructure.security.totp import Rfc6238TotpService

pytestmark = pytest.mark.unit

SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
NOW = 1_700_000_000.0


class Recorder:
    """Stands in for the module logger.

    structlog does not route through `caplog` under this project's
    configuration, and asserting on the real pipeline would be testing
    structlog rather than the drift check.
    """

    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict[str, Any]]] = []

    def warning(self, event: str, **fields: Any) -> None:
        self.warnings.append((event, fields))


@pytest.fixture
def totp() -> Rfc6238TotpService:
    return Rfc6238TotpService()


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    listener = Recorder()
    monkeypatch.setattr(totp_module, "logger", listener)
    return listener


def test_the_rfc_vectors_still_pass(totp: Rfc6238TotpService):
    """RFC 6238 appendix B. If this breaks, nothing else here matters."""
    eight = Rfc6238TotpService(digits=8)

    assert eight.code_at(secret=SECRET, timestamp=59) == "94287082"
    assert eight.code_at(secret=SECRET, timestamp=1_111_111_109) == "07081804"
    assert eight.code_at(secret=SECRET, timestamp=1_234_567_890) == "89005924"


def test_the_current_code_is_accepted(totp: Rfc6238TotpService):
    code = totp.code_at(secret=SECRET, timestamp=NOW)

    assert totp.verify(secret=SECRET, code=code, now=NOW)


@pytest.mark.parametrize("skew", [-30, 0, 30])
def test_one_step_either_side_is_accepted(totp: Rfc6238TotpService, skew: int):
    """Phones and servers are never exactly in step."""
    code = totp.code_at(secret=SECRET, timestamp=NOW + skew)

    assert totp.verify(secret=SECRET, code=code, now=NOW)


@pytest.mark.parametrize("skew", [-300, -60, 60, 300])
def test_further_out_is_still_refused(totp: Rfc6238TotpService, skew: int):
    """The whole point of not widening the window."""
    code = totp.code_at(secret=SECRET, timestamp=NOW + skew)

    assert not totp.verify(secret=SECRET, code=code, now=NOW)


def test_a_refusal_caused_by_drift_is_named(totp: Rfc6238TotpService, recorder: Recorder):
    """The diagnosis this exists for."""
    code = totp.code_at(secret=SECRET, timestamp=NOW + 300)

    assert not totp.verify(secret=SECRET, code=code, now=NOW)
    assert [event for event, _ in recorder.warnings] == ["totp.clock_drift_suspected"]


def test_the_log_says_which_way_and_how_far(totp: Rfc6238TotpService, recorder: Recorder):
    """"Something is wrong with the clock" still leaves somebody guessing at
    whether the server is ahead or behind."""
    code = totp.code_at(secret=SECRET, timestamp=NOW + 300)

    totp.verify(secret=SECRET, code=code, now=NOW)

    assert recorder.warnings[0][1]["drift_seconds"] == 300


def test_a_genuinely_wrong_code_says_nothing_about_clocks(
    totp: Rfc6238TotpService, recorder: Recorder
):
    """Otherwise the warning appears on every mistyped digit and stops meaning
    anything."""
    assert not totp.verify(secret=SECRET, code="000000", now=NOW)

    assert recorder.warnings == []


def test_malformed_input_is_refused_without_touching_the_secret(totp: Rfc6238TotpService):
    for candidate in ("", "12345", "1234567", "abcdef", "12 34 56 78"):
        assert not totp.verify(secret=SECRET, code=candidate, now=NOW)


def test_spaces_in_a_pasted_code_are_tolerated(totp: Rfc6238TotpService):
    """Authenticator apps display "123 456" and people copy what they see."""
    code = totp.code_at(secret=SECRET, timestamp=NOW)
    spaced = f"{code[:3]} {code[3:]}"

    assert totp.verify(secret=SECRET, code=spaced, now=NOW)
