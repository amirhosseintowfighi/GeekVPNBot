"""Access token issuing and verification."""

from __future__ import annotations

import uuid
from datetime import timedelta

import jwt as pyjwt
import pytest

from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.errors import TokenExpiredError, TokenInvalidError
from geekvpn.infrastructure.security.jwt import JwtAccessTokenService

SECRET = "a" * 48


def make_service(**overrides):
    kwargs = {
        "secret_key": SECRET,
        "issuer": "geekvpn",
        "audience": "geekvpn-clients",
        "ttl": timedelta(minutes=15),
    }
    kwargs.update(overrides)
    return JwtAccessTokenService(**kwargs)


def test_short_secrets_are_rejected_at_construction():
    with pytest.raises(ValueError, match="32"):
        make_service(secret_key="too-short")


def test_round_trip_preserves_every_claim():
    service = make_service()
    subject_id, session_id = uuid.uuid4(), uuid.uuid4()

    issued = service.issue(
        subject_type=SubjectType.ADMIN,
        subject_id=subject_id,
        session_id=session_id,
        role="support",
        permissions=["tickets.read", "tickets.reply"],
    )
    claims = service.decode(issued.value)

    assert claims.subject_type is SubjectType.ADMIN
    assert claims.subject_id == subject_id
    assert claims.session_id == session_id
    assert claims.role == "support"
    assert claims.permissions == ("tickets.read", "tickets.reply")


def test_a_token_signed_with_another_key_is_rejected():
    issued = make_service(secret_key="b" * 48).issue(
        subject_type=SubjectType.USER, subject_id=uuid.uuid4(), session_id=uuid.uuid4()
    )
    with pytest.raises(TokenInvalidError):
        make_service().decode(issued.value)


def test_expired_tokens_raise_the_expiry_error():
    service = make_service(ttl=timedelta(seconds=-120))
    issued = service.issue(
        subject_type=SubjectType.USER, subject_id=uuid.uuid4(), session_id=uuid.uuid4()
    )
    with pytest.raises(TokenExpiredError):
        service.decode(issued.value)


def test_wrong_audience_is_rejected():
    issued = make_service(audience="someone-else").issue(
        subject_type=SubjectType.USER, subject_id=uuid.uuid4(), session_id=uuid.uuid4()
    )
    with pytest.raises(TokenInvalidError):
        make_service().decode(issued.value)


def test_wrong_issuer_is_rejected():
    issued = make_service(issuer="evil").issue(
        subject_type=SubjectType.USER, subject_id=uuid.uuid4(), session_id=uuid.uuid4()
    )
    with pytest.raises(TokenInvalidError):
        make_service().decode(issued.value)


def test_the_none_algorithm_is_rejected():
    """CVE-2015-9235. Still attempted in the wild every single day."""
    forged = pyjwt.encode(
        {
            "iss": "geekvpn",
            "aud": "geekvpn-clients",
            "sub": str(uuid.uuid4()),
            "sid": str(uuid.uuid4()),
            "styp": "admin",
            "typ": "access",
            "jti": str(uuid.uuid4()),
            "iat": 1900000000,
            "exp": 1900003600,
            "perms": ["admins.write"],
        },
        key="",
        algorithm="none",
    )
    with pytest.raises(TokenInvalidError):
        make_service().decode(forged)


def test_a_non_access_token_type_is_rejected():
    token = pyjwt.encode(
        {
            "iss": "geekvpn",
            "aud": "geekvpn-clients",
            "sub": str(uuid.uuid4()),
            "sid": str(uuid.uuid4()),
            "styp": "user",
            "typ": "refresh",
            "jti": str(uuid.uuid4()),
            "iat": 1900000000,
            "exp": 1900003600,
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(TokenInvalidError):
        make_service().decode(token)


def test_garbage_is_rejected():
    with pytest.raises(TokenInvalidError):
        make_service().decode("not-a-token")
