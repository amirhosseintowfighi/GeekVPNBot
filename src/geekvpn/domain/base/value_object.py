"""Immutable, equality-by-value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ValueObject:
    """Marker base class.

    Subclasses stay frozen so they can be hashed, cached and shared safely.
    Invariants belong in ``__post_init__`` and raise ``ValidationError``.
    """
