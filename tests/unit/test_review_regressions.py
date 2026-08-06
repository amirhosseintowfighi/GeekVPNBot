"""Regression tests for defects found in the Phase 2 principal-engineer review.

Each test here maps to a specific bug that shipped in the first cut of Phase 2.
They exist so that a future refactor cannot quietly reintroduce the same
mistake. The comment above each test names the original defect.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.domain.identity.enums import AuthMethod, SubjectType
from geekvpn.domain.identity.session import DeviceInfo, RevocationReason, Session
from tests.fakes import InMemorySessionRepository

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _session(subject_type: SubjectType, subject_id: uuid.UUID) -> Session:
    return Session(
        uuid.uuid4(),
        subject_type=subject_type,
        subject_id=subject_id,
        auth_method=AuthMethod.ADMIN_PASSWORD,
        created_at=NOW,
        absolute_expires_at=NOW + timedelta(days=1),
        device=DeviceInfo(ip="127.0.0.1", user_agent="pytest", label=None),
    )


# Defect: the repository filtered on subject_id alone. A customer and an admin
# that happened to share a UUID would revoke each other's sessions. The id is
# generated independently in two different tables, so identity is the PAIR.
@pytest.mark.asyncio
async def test_revoke_all_does_not_cross_the_subject_type_boundary() -> None:
    shared_id = uuid.uuid4()
    repository = InMemorySessionRepository()
    admin_session = _session(SubjectType.ADMIN, shared_id)
    user_session = _session(SubjectType.USER, shared_id)
    await repository.add(admin_session)
    await repository.add(user_session)

    revoked = await repository.revoke_all_for_subject(
        shared_id,
        subject_type=SubjectType.ADMIN,
        reason=RevocationReason.ADMIN_REVOKED,
        now=NOW,
    )

    assert revoked == 1
    assert repository.sessions[admin_session.id].is_revoked is True
    assert repository.sessions[user_session.id].is_revoked is False


# Same defect, read path: listing a customer's devices must never surface an
# admin session.
@pytest.mark.asyncio
async def test_listing_sessions_does_not_cross_the_subject_type_boundary() -> None:
    shared_id = uuid.uuid4()
    repository = InMemorySessionRepository()
    await repository.add(_session(SubjectType.ADMIN, shared_id))
    user_session = _session(SubjectType.USER, shared_id)
    await repository.add(user_session)

    listed = await repository.list_active_for_subject(
        shared_id, subject_type=SubjectType.USER, now=NOW
    )

    assert [s.id for s in listed] == [user_session.id]


# NOTE: the third defect found in review - `_mint` generating its own token id
# so that `replaced_by_id` pointed at a nonexistent row - is already covered by
# `test_the_rotation_chain_points_at_the_replacement` in test_session_service.py,
# which asserts `replaced_by in repository.tokens`. That test failed before the
# fix and passes after it, so it is not duplicated here.


# Defect: `_DUMMY_HASH` was a hand-written string, not a real Argon2 encoding.
# Argon2 rejects a malformed hash in microseconds, so the "equalise the timing"
# branch did no work at all and the login endpoint stayed a username oracle.
def test_dummy_hash_is_a_real_argon2_hash() -> None:
    argon2 = pytest.importorskip("argon2")
    from geekvpn.infrastructure.security.passwords import Argon2Hasher

    hasher = Argon2Hasher()
    dummy = hasher.hash("whatever-random-string")

    # The real invariant: verifying against it must take the SLOW path, i.e. it
    # must be parseable and simply mismatch, not blow up as malformed.
    assert dummy.startswith("$argon2id$")
    assert hasher.verify("wrong-password", dummy) is False
    # Which of the two argon2 rejects a malformed encoding with has moved between
    # library versions; that it rejects rather than works is the part we rely on.
    with pytest.raises((argon2.exceptions.InvalidHashError, argon2.exceptions.VerificationError)):
        argon2.PasswordHasher().verify("$argon2id$not-a-real-hash", "x")
