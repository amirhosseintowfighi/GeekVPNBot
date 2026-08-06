"""RFC 6238 conformance and tolerance-window behaviour."""

from __future__ import annotations

import base64
import time

import pytest

from geekvpn.infrastructure.security.totp import Rfc6238TotpService

#: RFC 6238 Appendix B uses the ASCII seed "12345678901234567890".
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")


@pytest.fixture
def totp():
    return Rfc6238TotpService(digits=8)


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
    ],
)
def test_matches_the_rfc_test_vectors(totp, timestamp, expected):
    assert totp.code_at(secret=RFC_SECRET, timestamp=timestamp) == expected


def test_a_current_code_verifies():
    service = Rfc6238TotpService()
    now = time.time()
    assert service.verify(
        secret=RFC_SECRET, code=service.code_at(secret=RFC_SECRET, timestamp=now), now=now
    )


def test_the_previous_step_still_verifies():
    """One step of tolerance for clock skew and slow typing - no more."""
    service = Rfc6238TotpService()
    now = time.time()
    code = service.code_at(secret=RFC_SECRET, timestamp=now - 30)
    assert service.verify(secret=RFC_SECRET, code=code, now=now)


def test_a_code_three_steps_old_is_rejected():
    service = Rfc6238TotpService()
    now = time.time()
    code = service.code_at(secret=RFC_SECRET, timestamp=now - 120)
    assert not service.verify(secret=RFC_SECRET, code=code, now=now)


@pytest.mark.parametrize("bad", ["", "abcdef", "12345", "1234567", "   "])
def test_malformed_codes_are_rejected_without_raising(bad):
    assert not Rfc6238TotpService().verify(secret=RFC_SECRET, code=bad)


def test_generated_secrets_are_usable_and_unique():
    service = Rfc6238TotpService()
    first, second = service.generate_secret(), service.generate_secret()
    assert first != second
    now = time.time()
    assert service.verify(secret=first, code=service.code_at(secret=first, timestamp=now), now=now)


def test_provisioning_uri_is_well_formed():
    uri = Rfc6238TotpService().provisioning_uri(
        secret=RFC_SECRET, account="amir", issuer="Geek VPN"
    )
    assert uri.startswith("otpauth://totp/")
    assert f"secret={RFC_SECRET}" in uri
