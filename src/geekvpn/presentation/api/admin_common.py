"""Shared plumbing for the admin routers.

Three things every admin write needs, written once instead of once per router.

``read_scope`` / ``mutate_scope``
    The application services behind the admin panel are **synchronous**, so a
    coroutine cannot call them. Both helpers move the use case onto a worker
    thread; ``mutate_scope`` additionally owns the transaction, because the
    repositories deliberately never commit. That is what keeps "approve the
    payment, credit the wallet, write the audit row" a single atomic step.

``claim_idempotency``
    A reviewer double-clicking on a slow connection must not credit a wallet
    twice or send a customer two replies. The key is claimed in Redis *before*
    the work runs; recording it afterwards would leave open exactly the window
    that matters. A repeat is answered 409 rather than silently re-executed.

``admin_actor_id``
    The payments and support services identify an actor with an ``int`` while
    an administrator is a ``uuid.UUID``, and ``AdminModel`` has no integer
    surrogate. The only honest bridge is the linked Telegram id, so when there
    is none the request is refused rather than stamped with an invented
    identity that would sit on a money movement forever. ``SyncAuditLog``
    refuses the same coercion for the same reason.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, Query
from starlette.concurrency import run_in_threadpool

from geekvpn.domain.base.errors import ConflictError, NotFoundError, ValidationError
from geekvpn.infrastructure.di.sync_scope import SyncScope, build_sync_scope
from geekvpn.presentation.api.dependencies import ContainerDep
from geekvpn.presentation.api.security import CurrentAdmin, ScopeDep

#: The admin panel shows 25 rows per page everywhere. A single constant so the
#: envelope and the query default cannot drift apart.
ADMIN_PAGE_SIZE = 25

#: How long a used idempotency key is remembered: long enough to cover a retry
#: storm and an operator refreshing, short enough that keys do not accumulate.
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60

PageQuery = Annotated[int, Query(ge=1, le=10_000, description="1-based page number.")]

IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        description="Required on every mutation. A repeat of the same key is refused.",
    ),
]


async def admin_actor_id(admin: CurrentAdmin, scope: ScopeDep) -> int:
    """The acting administrator's numeric identity, or a refusal."""
    record = await scope.admins.get(admin.subject_id)
    if record is None:  # pragma: no cover - a live token for a deleted admin
        raise NotFoundError("This administrator account no longer exists.")
    if record.telegram_id is None:
        raise ValidationError(
            "برای این اقدام، حساب تلگرام مدیر باید متصل باشد.",
            admin_id=str(admin.subject_id),
        )
    return int(record.telegram_id)


ActorId = Annotated[int, Depends(admin_actor_id)]


async def claim_idempotency(container: ContainerDep, key: str, *, scope_label: str) -> None:
    """Claim an idempotency key, or reject the replay with 409."""
    claimed = await container.cache.add_if_absent(
        f"idem:{scope_label}:{key}",
        "1",
        ttl_seconds=IDEMPOTENCY_TTL_SECONDS,
    )
    if not claimed:
        raise ConflictError(
            "این درخواست پیش‌تر با همین کلید ثبت شده است.",
            idempotency_key=key,
        )


async def read_scope[T](container: ContainerDep, work: Callable[[SyncScope], T]) -> T:
    """Run a read-only use case off the event loop.

    Generic in the work's return type, so a router keeps the type it built
    instead of every admin endpoint decaying to ``Any`` at this boundary.
    """

    def _call() -> T:
        session = container.sync_sessions()
        try:
            return work(build_sync_scope(container, session))
        finally:
            session.close()

    return await run_in_threadpool(_call)


async def mutate_scope[T](container: ContainerDep, work: Callable[[SyncScope], T]) -> T:
    """Run a mutating use case off the event loop, owning the transaction."""

    def _call() -> T:
        session = container.sync_sessions()
        try:
            result = work(build_sync_scope(container, session))
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return await run_in_threadpool(_call)


__all__ = [
    "ADMIN_PAGE_SIZE",
    "IDEMPOTENCY_TTL_SECONDS",
    "ActorId",
    "IdempotencyKey",
    "PageQuery",
    "admin_actor_id",
    "claim_idempotency",
    "mutate_scope",
    "read_scope",
]
