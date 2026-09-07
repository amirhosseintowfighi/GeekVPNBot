"""A `/start ref_XXXX` link has to leave something behind.

The link worked. `ref_M7SFXQ3J` was parsed, resolved and stored on the invitee
as `referred_by_code` - and that is where it stopped. Five screens report the
programme, and every one of them counts rows in `referrals`: the customer's own
referral page, the operator's programme report and three analytics queries.
Nothing had ever inserted one, so a customer who really had invited somebody
was told "nobody has used your link yet".

The failure is the one this codebase keeps producing: a table with readers and
no writer, which looks like working code from every side.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from geekvpn.application.identity.authenticate_telegram import AuthenticateTelegramUser
from geekvpn.application.identity.dto import RequestContext
from geekvpn.application.ports.telegram_auth import TelegramIdentity
from geekvpn.domain.identity.enums import AuthMethod
from geekvpn.domain.identity.user import User

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 7, tzinfo=UTC)
CODE = "M7SFXQ3J"


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeUsers:
    def __init__(self, existing: list[User] | None = None) -> None:
        self.items = list(existing or [])

    async def get(self, user_id):
        return next((u for u in self.items if u.id == user_id), None)

    async def get_by_telegram_id(self, telegram_id, *, reseller_id=None):
        return next((u for u in self.items if u.telegram_id == telegram_id), None)

    async def get_by_referral_code(self, code):
        return next((u for u in self.items if u.referral_code == code), None)

    async def add(self, user):
        self.items.append(user)

    async def update(self, user):
        return None


class FakeReferrals:
    def __init__(self) -> None:
        self.edges: list[dict] = []

    async def record_signup(self, **kwargs) -> bool:
        if any(e["invitee_telegram_id"] == kwargs["invitee_telegram_id"] for e in self.edges):
            return False
        self.edges.append(kwargs)
        return True


class Broken(FakeReferrals):
    async def record_signup(self, **kwargs) -> bool:
        raise RuntimeError("down")


class FakeSessions:
    async def issue_pair(self, **kwargs):
        return None


class FakeVerifier:
    def verify_bot_update(self, identity):  # pragma: no cover - unused
        return identity


class FakeAudit:
    async def record(self, *args: object, **kwargs: object) -> None:
        return None


def _referrer() -> User:
    return User.register(
        user_id=uuid.uuid4(),
        telegram_id=111,
        referral_code=CODE,
        first_name="Referrer",
        now=NOW,
    )


def _service(users: FakeUsers, referrals=None) -> AuthenticateTelegramUser:
    return AuthenticateTelegramUser(
        users=users,
        verifier=FakeVerifier(),
        sessions=FakeSessions(),
        clock=FixedClock(),
        audit=FakeAudit(),
        referrals=referrals,
    )


def _arrive(service: AuthenticateTelegramUser, *, telegram_id: int, param: str | None):
    identity = TelegramIdentity(
        telegram_id=telegram_id,
        method=AuthMethod.TELEGRAM_BOT,
        first_name="Friend",
        start_param=param,
    )
    return asyncio.run(
        service.from_trusted_bot_update(identity, context=RequestContext(device_label="test"))
    )


def test_the_friend_who_used_the_link_becomes_an_edge():
    """The reported bug, end to end: they pressed start and the referrer's
    list stayed empty."""
    users = FakeUsers([_referrer()])
    referrals = FakeReferrals()

    _arrive(_service(users, referrals), telegram_id=222, param=f"ref_{CODE}")

    assert len(referrals.edges) == 1
    assert referrals.edges[0]["referrer_telegram_id"] == 111
    assert referrals.edges[0]["invitee_telegram_id"] == 222
    assert referrals.edges[0]["code"] == CODE


def test_the_edge_is_dated_when_they_arrived():
    users = FakeUsers([_referrer()])
    referrals = FakeReferrals()

    _arrive(_service(users, referrals), telegram_id=222, param=f"ref_{CODE}")

    assert referrals.edges[0]["joined_at"] == NOW


def test_somebody_arriving_with_no_link_makes_no_edge():
    users = FakeUsers([_referrer()])
    referrals = FakeReferrals()

    _arrive(_service(users, referrals), telegram_id=222, param=None)

    assert referrals.edges == []


def test_a_code_nobody_owns_makes_no_edge():
    """A mistyped or expired link is not a reason to invent a referrer."""
    users = FakeUsers([_referrer()])
    referrals = FakeReferrals()

    _arrive(_service(users, referrals), telegram_id=222, param="ref_NOTACODE")

    assert referrals.edges == []


def test_a_returning_customer_does_not_get_a_second_edge():
    """`/start` on a shared link is tapped more than once. The edge belongs to
    a registration, so the second tap - which finds an existing account - must
    not produce a second one; the repository refuses it as well, because the
    invitee column is unique and a duplicate insert would abort the very
    transaction somebody is being registered in."""
    users = FakeUsers([_referrer()])
    referrals = FakeReferrals()
    service = _service(users, referrals)

    _arrive(service, telegram_id=222, param=f"ref_{CODE}")
    _arrive(service, telegram_id=222, param=f"ref_{CODE}")

    assert len(referrals.edges) == 1


def test_a_broken_referral_store_does_not_cost_somebody_their_account():
    """Registration is the one thing that must survive. A bonus that fails to
    record can be fixed by hand; a customer who cannot sign up cannot."""
    users = FakeUsers([_referrer()])

    result = _arrive(_service(users, Broken()), telegram_id=222, param=f"ref_{CODE}")

    assert result.is_new_user
    assert users.items[-1].telegram_id == 222
