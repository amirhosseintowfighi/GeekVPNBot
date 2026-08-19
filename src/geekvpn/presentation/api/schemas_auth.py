"""Auth request/response models.

Separate from the application DTOs on purpose: this is the wire contract and it
is allowed to change independently of the domain.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import ConfigDict, Field

from geekvpn.presentation.api.base_schema import ApiModel


class MiniAppLoginRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    init_data: str = Field(
        min_length=1,
        max_length=8192,
        description="The raw `Telegram.WebApp.initData` string, unmodified.",
    )


class WidgetLoginRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    auth_date: str
    hash: str
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None


class AdminLoginRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    totp_code: str | None = Field(default=None, max_length=8)


class RefreshRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=16, max_length=512)


class TokenResponse(ApiModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"  # noqa: S105 - scheme name
    access_expires_at: datetime
    refresh_expires_at: datetime
    session_id: uuid.UUID


class UserResponse(ApiModel):
    id: uuid.UUID
    telegram_id: int
    display_name: str
    username: str | None
    language: str
    status: str
    referral_code: str
    is_premium: bool
    photo_url: str | None
    created_at: datetime | None


class AdminResponse(ApiModel):
    id: uuid.UUID
    username: str
    role: str
    permissions: list[str]
    is_totp_enabled: bool
    last_login_at: datetime | None


class UserLoginResponse(ApiModel):
    tokens: TokenResponse
    user: UserResponse
    is_new_user: bool


class AdminLoginResponse(ApiModel):
    tokens: TokenResponse
    admin: AdminResponse


class SessionResponse(ApiModel):
    id: uuid.UUID
    created_at: datetime
    last_used_at: datetime
    ip: str | None
    user_agent: str | None
    device_label: str | None
    is_current: bool


class MessageResponse(ApiModel):
    message: str


class AuditEntryResponse(ApiModel):
    id: uuid.UUID
    action: str
    outcome: str
    occurred_at: datetime
    actor_type: str
    actor_id: uuid.UUID | None
    actor_label: str | None
    target_type: str | None
    target_id: str | None
    ip: str | None
    correlation_id: str | None
    metadata: dict[str, object]


class SettingResponse(ApiModel):
    key: str
    value: object
    description: str | None
    is_secret: bool
    updated_at: datetime | None


class SettingUpdateRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    value: object
