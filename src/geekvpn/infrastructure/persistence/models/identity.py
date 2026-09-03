"""Identity tables.

Schema decisions worth defending:

* **UUID primary keys.** Ids appear in URLs, deep links and support tickets; a
  sequential integer leaks how many customers we have and lets anyone enumerate
  them. UUIDv4 is generated application-side so an aggregate has an id before
  it is ever persisted.
* **`telegram_id` is `BigInteger`.** Telegram ids already exceed 32 bits.
* **Enums stored as `VARCHAR` with a check constraint**, not native PostgreSQL
  `ENUM`. Adding a value to a native enum is a DDL statement that locks; adding
  one here is a check-constraint swap. A dump also stays readable.
* **Permission overrides as `JSONB` arrays.** They are read as a whole set,
  never queried element-wise, so a join table would be pure overhead.
* **Refresh tokens in their own table**, one row per rotation, with a unique
  index on the hash. That unique index is what makes reuse detection a lookup
  rather than a scan.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from geekvpn.domain.identity.enums import AdminStatus, AuthMethod, Language, SubjectType, UserStatus
from geekvpn.domain.identity.permissions import AdminRole
from geekvpn.domain.identity.session import DeviceInfo, RefreshToken, RevocationReason, Session
from geekvpn.infrastructure.persistence.base import Base, TimestampMixin


def _values(enum_type: type[enum.Enum]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum_type)


class UserModel(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    #: Unique per *shop*, not globally - see the two partial indexes below.
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: Which shop this person is a customer of. NULL is the platform's own bot,
    #: which is every row that predates resellers.
    reseller_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resellers.id", ondelete="SET NULL"), index=True
    )
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    #: The name the customer chose for themselves. Separate from
    #: `first_name` because that column is overwritten from the Telegram
    #: payload on every authentication.
    preferred_name: Mapped[str | None] = mapped_column(String(128))
    language: Mapped[str] = mapped_column(String(8), nullable=False, default=Language.FA.value)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=UserStatus.ACTIVE.value, index=True
    )
    is_premium: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    photo_url: Mapped[str | None] = mapped_column(String(512))
    referral_code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    referred_by_code: Mapped[str | None] = mapped_column(String(16), index=True)
    suspended_reason: Mapped[str | None] = mapped_column(String(256))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"status IN ({_values(UserStatus)})", name="users_status"),
        CheckConstraint(f"language IN ({_values(Language)})", name="users_language"),
        # Supports the "who did this user refer?" query without a scan.
        Index("ix_users_referred_by_code_status", "referred_by_code", "status"),
        # One row per Telegram account per shop. Two partial indexes rather
        # than one composite unique, because Postgres treats NULLs as distinct
        # - a composite would happily accept the same person twice as a
        # platform customer, which is the duplicate this exists to prevent.
        Index(
            "uq_users_platform_telegram_id",
            "telegram_id",
            unique=True,
            postgresql_where=text("reseller_id IS NULL"),
        ),
        Index(
            "uq_users_reseller_telegram_id",
            "reseller_id",
            "telegram_id",
            unique=True,
            postgresql_where=text("reseller_id IS NOT NULL"),
        ),
    )


class AdminModel(TimestampMixin, Base):
    __tablename__ = "admins"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(256), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AdminStatus.ACTIVE.value
    )
    granted_permissions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    denied_permissions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    is_totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: A one-time link that lets somebody set their own first password.
    #:
    #: Only a hash, for the same reason passwords are hashed: a database dump
    #: must not hand over somebody else's account. It is cleared the moment it
    #: is used, so a link shared by accident stops working once.
    setup_token_hash: Mapped[str | None] = mapped_column(String(128))
    setup_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"role IN ({_values(AdminRole)})", name="admins_role"),
        CheckConstraint(f"status IN ({_values(AdminStatus)})", name="admins_status"),
    )


class SessionModel(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    auth_method: Mapped[str] = mapped_column(String(32), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(45))  # IPv6-sized
    user_agent: Mapped[str | None] = mapped_column(String(512))
    device_label: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(32))

    refresh_tokens: Mapped[list[RefreshTokenModel]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    # -- mapping ----------------------------------------------------------
    #
    # The session repository was written against these and they did not exist,
    # so every login and every refresh failed on the first attribute access.
    # They live on the model rather than in a mapper module because that is
    # what the repository already expects.

    def to_domain(self) -> Session:
        return Session(
            self.id,
            subject_type=SubjectType(self.subject_type),
            subject_id=self.subject_id,
            auth_method=AuthMethod(self.auth_method),
            device=DeviceInfo(ip=self.ip, user_agent=self.user_agent, label=self.device_label),
            created_at=self.created_at,
            last_used_at=self.last_used_at,
            absolute_expires_at=self.absolute_expires_at,
            revoked_at=self.revoked_at,
            revocation_reason=(
                RevocationReason(self.revocation_reason) if self.revocation_reason else None
            ),
        )

    @classmethod
    def from_domain(cls, session: Session) -> SessionModel:
        model = cls(id=session.id)
        model.apply(session)
        return model

    def apply(self, session: Session) -> None:
        """Copy every mutable field across.

        Assignment rather than a fresh instance: the row may already be in the
        identity map, and replacing it there would detach the one the caller
        holds.
        """
        self.subject_type = session.subject_type.value
        self.subject_id = session.subject_id
        self.auth_method = session.auth_method.value
        self.ip = session.device.ip
        self.user_agent = session.device.user_agent
        self.device_label = session.device.label
        self.created_at = session.created_at
        self.last_used_at = session.last_used_at
        self.absolute_expires_at = session.absolute_expires_at
        self.revoked_at = session.revoked_at
        self.revocation_reason = (
            session.revocation_reason.value if session.revocation_reason else None
        )

    __table_args__ = (
        CheckConstraint(f"subject_type IN ({_values(SubjectType)})", name="sessions_subject"),
        CheckConstraint(
            f"revocation_reason IS NULL OR revocation_reason IN ({_values(RevocationReason)})",
            name="sessions_revocation_reason",
        ),
        # The "my active devices" query, served by one index.
        Index("ix_sessions_subject_id_revoked_at", "subject_id", "revoked_at"),
        Index("ix_sessions_absolute_expires_at", "absolute_expires_at"),
    )


class RefreshTokenModel(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: SHA-256 hex digest. The plaintext is never stored anywhere.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))

    session: Mapped[SessionModel] = relationship(back_populates="refresh_tokens", lazy="noload")

    def to_domain(self) -> RefreshToken:
        return RefreshToken(
            id=self.id,
            session_id=self.session_id,
            token_hash=self.token_hash,
            issued_at=self.issued_at,
            expires_at=self.expires_at,
            used_at=self.used_at,
            revoked_at=self.revoked_at,
            replaced_by_id=self.replaced_by_id,
        )

    @classmethod
    def from_domain(cls, token: RefreshToken) -> RefreshTokenModel:
        return cls(
            id=token.id,
            session_id=token.session_id,
            token_hash=token.token_hash,
            issued_at=token.issued_at,
            expires_at=token.expires_at,
            used_at=token.used_at,
            revoked_at=token.revoked_at,
            replaced_by_id=token.replaced_by_id,
        )

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
        Index("ix_refresh_tokens_session_id", "session_id"),
        Index("ix_refresh_tokens_expires_at", "expires_at"),
    )
