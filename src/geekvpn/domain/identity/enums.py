"""Closed vocabularies of the identity context.

These are `StrEnum`s so they serialise to readable strings in JWT claims, audit
rows and API responses, and so a database value stays intelligible to a human
reading a table dump at 3am.
"""

from __future__ import annotations

import enum


class UserStatus(enum.StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"

    @property
    def can_authenticate(self) -> bool:
        return self is UserStatus.ACTIVE


class AdminStatus(enum.StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"

    @property
    def can_authenticate(self) -> bool:
        return self is AdminStatus.ACTIVE


class Language(enum.StrEnum):
    FA = "fa"
    EN = "en"


class SubjectType(enum.StrEnum):
    """Who a session or an audit entry belongs to.

    Customers and admins are separate aggregates on purpose: an admin is not a
    customer with a flag. They authenticate differently, their sessions have
    different lifetimes, and conflating them is how privilege-escalation bugs
    are born.
    """

    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"


class AuthMethod(enum.StrEnum):
    TELEGRAM_MINI_APP = "telegram_mini_app"
    TELEGRAM_LOGIN_WIDGET = "telegram_login_widget"
    TELEGRAM_BOT = "telegram_bot"
    ADMIN_PASSWORD = "admin_password"  # noqa: S105 - a constant name, not a credential
    REFRESH = "refresh"
