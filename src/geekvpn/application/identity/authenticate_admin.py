"""Admin password login with lockout, 2FA and IP allow-listing.

Threat model: this endpoint is the highest-value target in the platform. It is
therefore the most defended thing in the codebase - rate limited by IP and by
username, locked after repeated failures, optionally restricted by network, and
2FA-mandatory for super admins.
"""

from __future__ import annotations

import secrets

from geekvpn.application.identity.dto import (
    AdminProfile,
    AuthenticationResult,
    RequestContext,
)
from geekvpn.application.identity.session_service import SessionService
from geekvpn.application.ports.audit import AuditRecorder
from geekvpn.application.ports.clock import Clock
from geekvpn.application.ports.ip_allowlist import IpAllowlistPort
from geekvpn.application.ports.passwords import PasswordHasher, TotpService
from geekvpn.application.ports.rate_limiter import RateLimiter
from geekvpn.application.ports.repositories import AdminRepository
from geekvpn.domain.audit.entry import AuditAction, AuditOutcome
from geekvpn.domain.identity.admin import Admin
from geekvpn.domain.identity.enums import AuthMethod, SubjectType
from geekvpn.domain.identity.errors import (
    AccountLockedError,
    InvalidCredentialsError,
    IpNotAllowedError,
    TwoFactorInvalidError,
    TwoFactorRequiredError,
)

#: Attempts allowed per window, per identifier.
LOGIN_RATE_LIMIT = 10
LOGIN_RATE_WINDOW_SECONDS = 300


class AuthenticateAdmin:
    def __init__(
        self,
        *,
        admins: AdminRepository,
        passwords: PasswordHasher,
        totp: TotpService,
        sessions: SessionService,
        clock: Clock,
        audit: AuditRecorder,
        rate_limiter: RateLimiter,
        allowlist: IpAllowlistPort | None = None,
    ) -> None:
        self._admins = admins
        self._passwords = passwords
        # Computed once, from the live hasher, so it is a REAL hash with the
        # current parameters. A hand-written constant would be rejected by
        # Argon2 as malformed in microseconds, which defeats the entire point
        # of verifying it (see `_dummy_verify`).
        self._dummy_hash = passwords.hash(secrets.token_urlsafe(32))
        self._totp = totp
        self._sessions = sessions
        self._clock = clock
        self._audit = audit
        self._rate_limiter = rate_limiter
        self._allowlist = allowlist

    async def execute(
        self,
        *,
        username: str,
        password: str,
        totp_code: str | None = None,
        context: RequestContext,
    ) -> AuthenticationResult:
        now = self._clock.now()
        username = username.strip().lower()

        self._enforce_ip_allowlist(context)
        await self._enforce_rate_limit(username=username, context=context)

        admin = await self._admins.get_by_username(username)

        # Verify a dummy hash when the admin does not exist so the response
        # time does not reveal whether the username is real.
        if admin is None:
            self._dummy_verify(password)
            await self._fail(username=username, context=context, reason="unknown_username")
            raise InvalidCredentialsError()

        try:
            admin.ensure_can_authenticate(now=now)
        except AccountLockedError:
            await self._fail(username=username, context=context, reason="locked", admin=admin)
            raise

        if not self._passwords.verify(password, admin.password_hash):
            admin.register_failed_attempt(now=now)
            await self._admins.update(admin)
            if admin.is_locked(now=now):
                await self._audit.record(
                    AuditAction.AUTH_ACCOUNT_LOCKED,
                    outcome=AuditOutcome.FAILURE,
                    actor_type=SubjectType.ADMIN,
                    actor_id=admin.id,
                    actor_label=admin.username,
                    ip=context.ip,
                )
            await self._fail(username=username, context=context, reason="bad_password", admin=admin)
            raise InvalidCredentialsError()

        await self._verify_second_factor(admin, totp_code, context)

        # Transparently upgrade the hash when Argon2 parameters change.
        if self._passwords.needs_rehash(admin.password_hash):
            admin.set_password_hash(self._passwords.hash(password), now=now)

        admin.register_successful_login(now=now)
        await self._admins.update(admin)

        permissions = tuple(sorted(permission.value for permission in admin.permissions))
        tokens = await self._sessions.issue_pair(
            subject_type=SubjectType.ADMIN,
            subject_id=admin.id,
            method=AuthMethod.ADMIN_PASSWORD,
            context=context,
            role=admin.role.value,
            permissions=permissions,
        )
        await self._audit.record(
            AuditAction.AUTH_LOGIN_SUCCEEDED,
            actor_type=SubjectType.ADMIN,
            actor_id=admin.id,
            actor_label=admin.username,
            ip=context.ip,
            user_agent=context.user_agent,
            role=admin.role.value,
        )
        return AuthenticationResult(
            tokens=tokens,
            subject_type=SubjectType.ADMIN,
            method=AuthMethod.ADMIN_PASSWORD,
            admin=AdminProfile(
                id=admin.id,
                username=admin.username,
                role=admin.role.value,
                permissions=permissions,
                is_totp_enabled=admin.is_totp_enabled,
                last_login_at=admin.last_login_at,
            ),
        )

    # -- guards ------------------------------------------------------------

    def _dummy_verify(self, password: str) -> None:
        """Burn the same CPU as a real verification.

        Without this, "no such admin" returns in microseconds while a wrong
        password costs a full 64 MiB Argon2 pass. That difference is trivially
        measurable over the network and turns the login endpoint into a
        username oracle.
        """
        self._passwords.verify(password, self._dummy_hash)

    def _enforce_ip_allowlist(self, context: RequestContext) -> None:
        """Refuse addresses outside the configured networks.

        Delegated to the allowlist rather than compared as strings: an operator
        who writes ``10.0.0.0/8`` means the range, and an address we could not
        establish (``context.ip is None``) must be refused, not let through.
        """
        if self._allowlist is None or self._allowlist.is_empty:
            return
        if not self._allowlist.allows(context.ip):
            raise IpNotAllowedError()

    async def _enforce_rate_limit(self, *, username: str, context: RequestContext) -> None:
        """Limit by username and by IP.

        By username alone, a botnet walks straight past it. By IP alone, one
        office NAT locks out the whole team. Both, and neither hole is open.
        """
        keys = [f"admin-login:user:{username}"]
        if context.ip:
            keys.append(f"admin-login:ip:{context.ip}")
        for key in keys:
            verdict = await self._rate_limiter.hit(
                key, limit=LOGIN_RATE_LIMIT, window_seconds=LOGIN_RATE_WINDOW_SECONDS
            )
            if not verdict.allowed:
                raise AccountLockedError(retry_after_seconds=verdict.retry_after_seconds)

    async def _verify_second_factor(
        self, admin: Admin, totp_code: str | None, context: RequestContext
    ) -> None:
        if not admin.requires_totp:
            return
        if not admin.totp_secret:
            # A super admin without an enrolled secret cannot be let in with a
            # password alone; enrolment happens out of band.
            raise TwoFactorRequiredError(enrolment_required=True)
        if not totp_code:
            raise TwoFactorRequiredError()
        if not self._totp.verify(secret=admin.totp_secret, code=totp_code):
            await self._audit.record(
                AuditAction.AUTH_TOTP_FAILED,
                outcome=AuditOutcome.FAILURE,
                actor_type=SubjectType.ADMIN,
                actor_id=admin.id,
                actor_label=admin.username,
                ip=context.ip,
            )
            raise TwoFactorInvalidError()

    async def _fail(
        self,
        *,
        username: str,
        context: RequestContext,
        reason: str,
        admin: Admin | None = None,
    ) -> None:
        await self._audit.record(
            AuditAction.AUTH_LOGIN_FAILED,
            outcome=AuditOutcome.FAILURE,
            actor_type=SubjectType.ADMIN,
            actor_id=admin.id if admin else None,
            actor_label=username,
            ip=context.ip,
            user_agent=context.user_agent,
            reason=reason,
        )
