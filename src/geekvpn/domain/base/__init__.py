"""Building blocks every bounded context reuses."""

from geekvpn.domain.base.entity import AggregateRoot, Entity
from geekvpn.domain.base.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from geekvpn.domain.base.events import DomainEvent
from geekvpn.domain.base.value_object import ValueObject

__all__ = [
    "AggregateRoot",
    "ConflictError",
    "DomainError",
    "DomainEvent",
    "Entity",
    "NotFoundError",
    "PermissionDeniedError",
    "ValidationError",
    "ValueObject",
]
