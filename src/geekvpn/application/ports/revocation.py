"""Session revocation list.

The problem this solves: access tokens are self-contained and short-lived, so
nothing checks the database on a normal request. That is what makes the API
fast, and it means a revoked session would otherwise keep working until its
access token expires.

For customers, waiting out a 15-minute token is fine. For an admin whose
account was just compromised, it is not. So revocations are published to a
tiny Redis structure that the auth dependency checks on every request:

* `session:<sid>` - this one session is dead;
* `subject:<id>`  - every token for this subject issued before time T is dead
  (the "logout everywhere" epoch).

Keys expire on their own after the maximum access-token lifetime, so the
structure stays small no matter how many sessions have ever existed.

It fails **open**: if Redis is unavailable the request proceeds, because the
alternative is that a Redis blip logs out every user of the platform. The
window is bounded by the access-token TTL, and the event is logged loudly.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class RevocationList(Protocol):
    async def revoke_session(self, session_id: uuid.UUID, *, ttl_seconds: int) -> None: ...

    async def revoke_subject(
        self, subject_id: uuid.UUID, *, at: datetime, ttl_seconds: int
    ) -> None: ...

    async def is_revoked(
        self, *, session_id: uuid.UUID, subject_id: uuid.UUID, issued_at: datetime
    ) -> bool: ...
