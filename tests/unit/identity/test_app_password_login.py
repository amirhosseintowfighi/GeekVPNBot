"""Android app sign-in with a username and password set in the bot (`AppPasswordLogin`)."""

from __future__ import annotations

import uuid

import pytest
from tests.conftest import FastHasher
from tests.fakes import InMemoryAppCredentialRepository
from tests.unit.identity.test_app_link_login import CONTEXT, World

from geekvpn.application.identity.app_link_login import APP_AUTH_METHODS
from geekvpn.application.identity.app_password_login import AppLoginDevice, AppPasswordLogin
from geekvpn.domain.base.errors import RateLimitedError
from geekvpn.domain.identity.enums import AuthMethod, SubjectType
from geekvpn.domain.identity.errors import (
    AccountSuspendedError,
    AppPasswordWeakError,
    AppUsernameInvalidError,
    AppUsernameTakenError,
    InvalidCredentialsError,
)

pytestmark = pytest.mark.unit

DEVICE = AppLoginDevice(name="Galaxy A54", platform="android", app_version="0.2.0")


class CountingHasher(FastHasher):
    def __init__(self) -> None:
        self.verified: list[str] = []

    def verify(self, password: str, password_hash: str) -> bool:
        self.verified.append(password_hash)
        return super().verify(password, password_hash)


class PasswordWorld(World):
    def __init__(self, *, rate_limited: bool = False) -> None:
        super().__init__(rate_limited=rate_limited)
        self.credentials = InMemoryAppCredentialRepository()
        self.hasher = CountingHasher()
        self.password_login = AppPasswordLogin(
            credentials=self.credentials,
            users=self.users,
            passwords=self.hasher,
            sessions=self.sessions,
            session_records=self.session_records,
            rate_limiter=self.rate_limiter,
            clock=self.clock,
            audit=self.login._audit,
        )

    async def sign_in(
        self,
        username: str = "ali_92",
        password: str = "correct horse",  # noqa: S107 - a test fixture
    ):
        return await self.password_login.login(
            username=username, password=password, device=DEVICE, context=CONTEXT
        )


# -- setting a password in the bot --------------------------------------------


async def test_a_customer_sets_a_username_and_only_a_hash_is_kept() -> None:
    world = PasswordWorld()
    user = await world.customer()

    stored = await world.password_login.set_credentials(
        user.id, username="  Ali_92 ", password="correct horse"
    )

    assert stored == "ali_92"
    credential = world.credentials.items[user.id]
    assert credential.username == "ali_92"
    assert credential.password_hash != "correct horse"
    assert await world.password_login.username_of(user.id) == "ali_92"


@pytest.mark.parametrize("username", ["abc", "1abc", "ali-92", "علی_۹۲", "a" * 33, ""])
async def test_usernames_outside_the_rules_are_refused(username: str) -> None:
    world = PasswordWorld()
    user = await world.customer()

    with pytest.raises(AppUsernameInvalidError):
        await world.password_login.set_credentials(user.id, username=username, password="x" * 12)


@pytest.mark.parametrize("password", ["short", "x" * 129, "ali_92", "ALI_92  "])
async def test_short_long_or_username_passwords_are_refused(password: str) -> None:
    world = PasswordWorld()
    user = await world.customer()

    with pytest.raises(AppPasswordWeakError):
        await world.password_login.set_credentials(user.id, username="ali_92", password=password)
    assert user.id not in world.credentials.items


async def test_a_username_held_by_another_customer_is_refused_before_the_password() -> None:
    world = PasswordWorld()
    first = await world.customer(telegram_id=1)
    second = await world.customer(telegram_id=2)
    await world.password_login.set_credentials(first.id, username="ali_92", password="x" * 12)

    with pytest.raises(AppUsernameTakenError):
        await world.password_login.is_available("ALI_92", user_id=second.id)
    with pytest.raises(AppUsernameTakenError):
        await world.password_login.set_credentials(second.id, username="ali_92", password="y" * 12)
    # Keeping one's own name while changing the password is fine.
    assert await world.password_login.is_available("ali_92", user_id=first.id) == "ali_92"


async def test_a_resellers_customer_cannot_set_an_app_password() -> None:
    world = PasswordWorld()
    user = await world.customer()
    user.reseller_id = "shop"

    with pytest.raises(AppUsernameInvalidError):
        await world.password_login.set_credentials(user.id, username="ali_92", password="x" * 12)


async def test_changing_the_password_signs_out_phones_that_used_the_old_one() -> None:
    world = PasswordWorld()
    user = await world.customer()
    await world.password_login.set_credentials(user.id, username="ali_92", password="old password")
    old = await world.sign_in(password="old password")
    # A Telegram-approved phone is not the password's to sign out.
    telegram_phone = await world.sessions.issue_pair(
        subject_type=SubjectType.USER,
        subject_id=user.id,
        method=AuthMethod.TELEGRAM_APP_LINK,
        context=CONTEXT,
    )

    await world.password_login.set_credentials(user.id, username="ali_92", password="new password")

    assert world.session_records.sessions[old.tokens.session_id].is_revoked
    assert not world.session_records.sessions[telegram_phone.session_id].is_revoked
    with pytest.raises(InvalidCredentialsError):
        await world.sign_in(password="old password")
    assert (await world.sign_in(password="new password")).user is not None


async def test_removing_the_password_signs_out_and_stops_future_logins() -> None:
    world = PasswordWorld()
    user = await world.customer()
    await world.password_login.set_credentials(user.id, username="ali_92", password="x" * 12)
    signed_in = await world.sign_in(password="x" * 12)

    assert await world.password_login.remove_credentials(user.id)

    assert world.session_records.sessions[signed_in.tokens.session_id].is_revoked
    assert await world.password_login.username_of(user.id) is None
    with pytest.raises(InvalidCredentialsError):
        await world.sign_in(password="x" * 12)
    assert not await world.password_login.remove_credentials(user.id)


# -- signing in from the app --------------------------------------------------


async def test_the_right_password_issues_a_customer_session_named_after_the_phone() -> None:
    world = PasswordWorld()
    user = await world.customer()
    await world.password_login.set_credentials(user.id, username="ali_92", password="correct horse")

    result = await world.sign_in(username="ALI_92", password="correct horse")

    assert result.method is AuthMethod.APP_PASSWORD
    assert result.user is not None and result.user.id == user.id
    session = world.session_records.sessions[result.tokens.session_id]
    assert session.subject_id == user.id
    assert session.device.label == "Galaxy A54"
    assert session.auth_method in APP_AUTH_METHODS


async def test_the_bots_device_list_shows_password_phones_and_can_cut_them() -> None:
    world = PasswordWorld()
    user = await world.customer()
    await world.password_login.set_credentials(user.id, username="ali_92", password="x" * 12)
    result = await world.sign_in(password="x" * 12)

    devices = await world.login.devices(user.id)
    assert [device.name for device in devices] == ["Galaxy A54"]
    assert await world.login.disconnect(user.id, result.tokens.session_id)


async def test_a_wrong_password_and_an_unknown_username_fail_the_same_way() -> None:
    world = PasswordWorld()
    user = await world.customer()
    await world.password_login.set_credentials(user.id, username="ali_92", password="x" * 12)
    world.hasher.verified.clear()

    with pytest.raises(InvalidCredentialsError):
        await world.sign_in(password="y" * 12)
    with pytest.raises(InvalidCredentialsError):
        await world.sign_in(username="nobody_here", password="y" * 12)
    with pytest.raises(InvalidCredentialsError):
        await world.sign_in(username="not a username!", password="y" * 12)

    # Every attempt paid for one verification, so timing does not tell them apart.
    assert len(world.hasher.verified) == 3


async def test_an_absurdly_long_password_is_refused_without_hashing_it() -> None:
    world = PasswordWorld()
    user = await world.customer()
    await world.password_login.set_credentials(user.id, username="ali_92", password="x" * 12)
    world.hasher.verified.clear()

    with pytest.raises(InvalidCredentialsError):
        await world.sign_in(password="x" * 1000)
    assert world.hasher.verified == []


async def test_a_suspended_customer_cannot_sign_in_with_the_right_password() -> None:
    world = PasswordWorld()
    user = await world.customer()
    await world.password_login.set_credentials(user.id, username="ali_92", password="x" * 12)
    user.suspend(reason="abuse")

    with pytest.raises(AccountSuspendedError):
        await world.sign_in(password="x" * 12)


async def test_attempts_are_limited_per_username_and_per_ip() -> None:
    world = PasswordWorld(rate_limited=True)

    with pytest.raises(RateLimitedError):
        await world.sign_in()
    assert world.rate_limiter.hits[0] == "app-password:user:ali_92"


async def test_the_rate_limit_key_is_the_normalised_username() -> None:
    world = PasswordWorld()
    with pytest.raises(InvalidCredentialsError):
        await world.sign_in(username="  ALI_92 ")
    assert world.rate_limiter.hits == ["app-password:user:ali_92", "app-password:ip:5.6.7.8"]


async def test_a_deleted_account_behind_a_credential_is_just_invalid() -> None:
    world = PasswordWorld()
    user = await world.customer()
    await world.password_login.set_credentials(user.id, username="ali_92", password="x" * 12)
    world.users.items.pop(user.id)

    with pytest.raises(InvalidCredentialsError):
        await world.sign_in(password="x" * 12)


async def test_setting_a_password_for_an_unknown_account_is_refused() -> None:
    world = PasswordWorld()
    with pytest.raises(AppUsernameInvalidError):
        await world.password_login.set_credentials(
            uuid.uuid4(), username="ali_92", password="x" * 12
        )
