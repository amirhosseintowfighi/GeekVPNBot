"""Session lifecycle: issue, rotate, detect reuse, revoke.

The highest-value tests in this phase. If refresh rotation regresses, a stolen
token becomes permanent access and nothing else in the system notices.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from geekvpn.application.identity.dto import RequestContext
from geekvpn.application.identity.session_service import SessionPolicy, SessionService
from geekvpn.domain.audit.entry import AuditAction
from geekvpn.domain.identity.enums import AuthMethod, SubjectType
from geekvpn.domain.identity.errors import (
    SessionRevokedError,
    TokenExpiredError,
    TokenInvalidError,
    TokenReuseDetectedError,
)
from geekvpn.domain.identity.session import RevocationReason
from geekvpn.infrastructure.security.jwt import JwtAccessTokenService
from geekvpn.infrastructure.security.refresh_tokens import Sha256RefreshTokenFactory
from tests.fakes import (
    FrozenClock,
    InMemoryRevocationList,
    InMemorySessionRepository,
    RecordingAudit,
)

CONTEXT = RequestContext(ip="1.2.3.4", user_agent="pytest")


async def no_role(subject_type, subject_id):
    return None, ()


def build_service():
    clock = FrozenClock()
    repository = InMemorySessionRepository()
    audit = RecordingAudit()
    revocations = InMemoryRevocationList()
    service = SessionService(
        sessions=repository,
        access_tokens=JwtAccessTokenService(
            secret_key="k" * 48,
            issuer="geekvpn",
            audience="geekvpn-clients",
            ttl=timedelta(minutes=15),
        ),
        refresh_tokens=Sha256RefreshTokenFactory(),
        clock=clock,
        audit=audit,
        revocations=revocations,
        user_policy=SessionPolicy(refresh_ttl=timedelta(days=30), absolute_ttl=timedelta(days=180)),
        admin_policy=SessionPolicy(
            refresh_ttl=timedelta(hours=12), absolute_ttl=timedelta(hours=24)
        ),
        access_ttl_seconds=900,
    )
    return service, repository, audit, revocations, clock


@pytest.fixture
def parts():
    return build_service()


async def issue(service, subject_type=SubjectType.USER, subject_id=None):
    return await service.issue_pair(
        subject_type=subject_type,
        subject_id=subject_id or uuid.uuid4(),
        method=AuthMethod.TELEGRAM_MINI_APP,
        context=CONTEXT,
    )


async def test_issuing_creates_a_session_and_stores_only_a_hash(parts):
    service, repository, _, _, _ = parts
    pair = await issue(service)

    assert pair.session_id in repository.sessions
    stored = next(iter(repository.tokens.values()))
    assert stored.token_hash != pair.refresh_token
    assert len(stored.token_hash) == 64


async def test_admin_sessions_are_shorter_than_customer_sessions(parts):
    service, repository, _, _, _ = parts
    user_pair = await issue(service, SubjectType.USER)
    admin_pair = await issue(service, SubjectType.ADMIN)

    assert (
        repository.sessions[admin_pair.session_id].absolute_expires_at
        < repository.sessions[user_pair.session_id].absolute_expires_at
    )


async def test_rotation_issues_a_new_pair_and_keeps_the_session(parts):
    service, repository, _, _, _ = parts
    first = await issue(service)

    outcome = await service.rotate(
        refresh_token=first.refresh_token, context=CONTEXT, role_resolver=no_role
    )

    assert outcome.tokens.refresh_token != first.refresh_token
    assert outcome.tokens.session_id == first.session_id
    assert len(repository.sessions) == 1


async def test_the_rotation_chain_points_at_the_replacement(parts):
    """`replaced_by_id` must be the id of the token actually issued, otherwise
    an incident responder cannot follow the chain."""
    service, repository, _, _, _ = parts
    first = await issue(service)
    old_id = next(iter(repository.tokens))

    await service.rotate(refresh_token=first.refresh_token, context=CONTEXT, role_resolver=no_role)

    replaced_by = repository.tokens[old_id].replaced_by_id
    assert replaced_by is not None
    assert replaced_by in repository.tokens


async def test_reusing_a_rotated_token_destroys_the_whole_session(parts):
    service, repository, audit, revocations, _ = parts
    first = await issue(service)
    await service.rotate(refresh_token=first.refresh_token, context=CONTEXT, role_resolver=no_role)

    with pytest.raises(TokenReuseDetectedError):
        await service.rotate(
            refresh_token=first.refresh_token, context=CONTEXT, role_resolver=no_role
        )

    session = repository.sessions[first.session_id]
    assert session.is_revoked
    assert session.revocation_reason is RevocationReason.TOKEN_REUSE
    assert AuditAction.AUTH_TOKEN_REUSE_DETECTED in audit.actions()
    assert first.session_id in revocations.revoked_sessions


async def test_the_newer_token_also_dies_when_reuse_is_detected(parts):
    """Containment: we cannot tell victim from thief, so nobody keeps access."""
    service, _, _, _, _ = parts
    first = await issue(service)
    second = await service.rotate(
        refresh_token=first.refresh_token, context=CONTEXT, role_resolver=no_role
    )

    with pytest.raises(TokenReuseDetectedError):
        await service.rotate(
            refresh_token=first.refresh_token, context=CONTEXT, role_resolver=no_role
        )
    with pytest.raises((SessionRevokedError, TokenReuseDetectedError)):
        await service.rotate(
            refresh_token=second.tokens.refresh_token,
            context=CONTEXT,
            role_resolver=no_role,
        )


async def test_an_unknown_token_is_rejected(parts):
    service, _, _, _, _ = parts
    with pytest.raises(TokenInvalidError):
        await service.rotate(refresh_token="never-issued", context=CONTEXT, role_resolver=no_role)


async def test_an_expired_refresh_token_is_rejected(parts):
    service, _, _, _, clock = parts
    pair = await issue(service)
    clock.advance(timedelta(days=31))

    with pytest.raises(TokenExpiredError):
        await service.rotate(
            refresh_token=pair.refresh_token, context=CONTEXT, role_resolver=no_role
        )


async def test_a_refresh_token_never_outlives_the_absolute_cap(parts):
    service, repository, _, _, _ = parts
    pair = await issue(service, SubjectType.ADMIN)
    assert pair.refresh_expires_at <= repository.sessions[pair.session_id].absolute_expires_at


async def test_revoking_a_session_stops_refresh_and_publishes_it(parts):
    service, _, audit, revocations, _ = parts
    pair = await issue(service)

    await service.revoke(pair.session_id)

    assert pair.session_id in revocations.revoked_sessions
    assert AuditAction.AUTH_LOGOUT in audit.actions()
    with pytest.raises((SessionRevokedError, TokenReuseDetectedError)):
        await service.rotate(
            refresh_token=pair.refresh_token, context=CONTEXT, role_resolver=no_role
        )


async def test_revoking_twice_is_harmless(parts):
    service, _, _, _, _ = parts
    pair = await issue(service)
    await service.revoke(pair.session_id)
    await service.revoke(pair.session_id)


async def test_revoke_all_kills_every_device_and_sets_an_epoch(parts):
    service, _, _, revocations, _ = parts
    subject_id = uuid.uuid4()
    await issue(service, subject_id=subject_id)
    await issue(service, subject_id=subject_id)

    count = await service.revoke_all(subject_type=SubjectType.USER, subject_id=subject_id)

    assert count == 2
    assert subject_id in revocations.revoked_subjects


async def test_revoke_all_can_spare_the_current_device(parts):
    service, repository, _, _, _ = parts
    subject_id = uuid.uuid4()
    keep = await issue(service, subject_id=subject_id)
    await issue(service, subject_id=subject_id)

    count = await service.revoke_all(
        subject_type=SubjectType.USER,
        subject_id=subject_id,
        except_session_id=keep.session_id,
    )

    assert count == 1
    assert not repository.sessions[keep.session_id].is_revoked
