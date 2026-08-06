"""The domain building blocks other contexts will inherit from."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from geekvpn.domain.base.entity import AggregateRoot, Entity
from geekvpn.domain.base.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationError,
)
from geekvpn.domain.base.events import DomainEvent

pytestmark = pytest.mark.unit


class _User(Entity[int]):
    pass


class _Other(Entity[int]):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class _Registered(DomainEvent):
    name = "identity.user.registered.v1"
    user_id: int

    def payload(self) -> dict[str, int]:
        return {"user_id": self.user_id}


class _Account(AggregateRoot[int]):
    pass


def test_entities_compare_by_identity() -> None:
    assert _User(1) == _User(1)
    assert _User(1) != _User(2)
    assert len({_User(1), _User(1)}) == 1


def test_entities_of_different_types_are_never_equal() -> None:
    assert _User(1) != _Other(1)


def test_aggregate_collects_and_clears_events() -> None:
    account = _Account(1)
    account.record(_Registered(user_id=1))

    collected = account.collect_events()

    assert len(collected) == 1
    assert collected[0].payload() == {"user_id": 1}
    assert account.collect_events() == []  # events are drained exactly once


def test_events_are_timestamped_in_utc_and_uniquely_identified() -> None:
    first, second = _Registered(user_id=1), _Registered(user_id=1)
    assert first.event_id != second.event_id
    assert first.occurred_at.tzinfo is UTC
    assert first.occurred_at <= datetime.now(UTC)


@pytest.mark.parametrize(
    ("error_type", "code"),
    [
        (ValidationError, "validation_error"),
        (NotFoundError, "not_found"),
        (ConflictError, "conflict"),
    ],
)
def test_domain_errors_expose_stable_codes(error_type: type[DomainError], code: str) -> None:
    error = error_type()
    assert error.code == code
    assert isinstance(error, DomainError)


def test_domain_error_carries_details() -> None:
    error = NotFoundError("No such plan.", plan_id=42)
    assert error.message == "No such plan."
    assert error.details == {"plan_id": 42}
