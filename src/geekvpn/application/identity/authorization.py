"""Permission checking.

One function, used by every guarded endpoint. Authorisation failures are
audited: an attempt to reach something you are not allowed to reach is a
security event, not a 403 to be quietly discarded.
"""

from __future__ import annotations

from collections.abc import Iterable

from geekvpn.application.ports.audit import AuditRecorder
from geekvpn.domain.audit.entry import AuditAction, AuditOutcome
from geekvpn.domain.identity.errors import MissingPermissionError
from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.identity.session import AuthenticatedSubject


def has_permissions(
    subject: AuthenticatedSubject,
    required: Iterable[Permission],
    *,
    require_all: bool = True,
) -> bool:
    needed = {permission.value for permission in required}
    if not needed:
        return True
    held = subject.permissions
    return needed <= held if require_all else bool(needed & held)


class AuthorizationService:
    def __init__(self, *, audit: AuditRecorder) -> None:
        self._audit = audit

    async def authorize(
        self,
        subject: AuthenticatedSubject,
        *required: Permission,
        require_all: bool = True,
        resource: str | None = None,
    ) -> None:
        if has_permissions(subject, required, require_all=require_all):
            return
        missing = sorted(
            permission.value
            for permission in required
            if permission.value not in subject.permissions
        )
        await self._audit.record(
            AuditAction.AUTH_PERMISSION_DENIED,
            outcome=AuditOutcome.FAILURE,
            actor_type=subject.subject_type,
            actor_id=subject.subject_id,
            target_type="endpoint",
            target_id=resource,
            missing_permissions=missing,
            role=subject.role,
        )
        raise MissingPermissionError(required=missing)
