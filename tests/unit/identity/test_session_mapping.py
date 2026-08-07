"""Sessions and refresh tokens must survive a round trip through the model.

The repository was written against `to_domain`, `from_domain` and `apply`, and
none of the three existed. Every login and every token refresh therefore failed
on the first attribute access - the kind of gap that only shows up once
something actually calls the repository.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from geekvpn.domain.identity.enums import AuthMethod, SubjectType
from geekvpn.domain.identity.session import (
    DeviceInfo,
    RefreshToken,
    RevocationReason,
    Session,
)
from geekvpn.infrastructure.persistence.models.identity import (
    RefreshTokenModel,
    SessionModel,
)

NOW = datetime(2026, 8, 7, tzinfo=UTC)


def make_session(**overrides: object) -> Session:
    fields: dict[str, object] = {
        "subject_type": SubjectType.USER,
        "subject_id": uuid.uuid4(),
        "auth_method": AuthMethod.TELEGRAM_MINI_APP,
        "device": DeviceInfo(ip="1.2.3.4", user_agent="Mozilla", label="iPhone"),
        "created_at": NOW,
        "last_used_at": NOW,
        "absolute_expires_at": NOW + timedelta(days=180),
    }
    fields.update(overrides)
    return Session(uuid.uuid4(), **fields)  # type: ignore[arg-type]


def test_a_session_survives_a_round_trip() -> None:
    original = make_session()

    restored = SessionModel.from_domain(original).to_domain()

    assert restored.id == original.id
    assert restored.subject_type is original.subject_type
    assert restored.subject_id == original.subject_id
    assert restored.auth_method is original.auth_method
    assert restored.absolute_expires_at == original.absolute_expires_at


def test_the_device_details_survive_the_round_trip() -> None:
    """The active-devices screen is built entirely from these three fields."""
    original = make_session()

    restored = SessionModel.from_domain(original).to_domain()

    assert restored.device.ip == "1.2.3.4"
    assert restored.device.user_agent == "Mozilla"
    assert restored.device.label == "iPhone"


def test_a_revoked_session_keeps_its_reason() -> None:
    original = make_session(revoked_at=NOW, revocation_reason=RevocationReason.TOKEN_REUSE)

    restored = SessionModel.from_domain(original).to_domain()

    assert restored.revoked_at == NOW
    assert restored.revocation_reason is RevocationReason.TOKEN_REUSE


def test_an_unrevoked_session_has_no_reason() -> None:
    """An empty string here would deserialise into an invalid enum member."""
    restored = SessionModel.from_domain(make_session()).to_domain()

    assert restored.revoked_at is None
    assert restored.revocation_reason is None


def test_apply_updates_the_existing_row_rather_than_replacing_it() -> None:
    """The row may already be in the identity map; swapping it would detach the
    instance the caller is holding."""
    original = make_session()
    model = SessionModel.from_domain(original)

    original.revoke(reason=RevocationReason.LOGOUT, now=NOW)
    model.apply(original)

    assert model.revoked_at is not None
    assert model.revocation_reason == RevocationReason.LOGOUT.value


def test_a_refresh_token_survives_a_round_trip() -> None:
    token = RefreshToken(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        token_hash="a" * 64,
        issued_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )

    restored = RefreshTokenModel.from_domain(token).to_domain()

    assert restored.id == token.id
    assert restored.session_id == token.session_id
    assert restored.token_hash == token.token_hash
    assert restored.used_at is None
    assert restored.replaced_by_id is None


def test_a_rotated_token_remembers_what_replaced_it() -> None:
    """Reuse detection walks this link; losing it loses the detection."""
    successor = uuid.uuid4()
    token = RefreshToken(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        token_hash="b" * 64,
        issued_at=NOW,
        expires_at=NOW + timedelta(days=30),
        used_at=NOW,
        replaced_by_id=successor,
    )

    restored = RefreshTokenModel.from_domain(token).to_domain()

    assert restored.used_at == NOW
    assert restored.replaced_by_id == successor
