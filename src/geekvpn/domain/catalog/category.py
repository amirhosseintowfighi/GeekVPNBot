"""Categories: how the storefront is grouped.

A category is presentation, not policy. It carries no price and no capability -
it exists so the Mini App can render "Direct" and "Tunnel" as two tabs. Keeping
it deliberately thin is what stops it from slowly becoming a second product
table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from geekvpn.domain.base.entity import AggregateRoot
from geekvpn.domain.catalog.enums import PublicationState
from geekvpn.domain.catalog.errors import CatalogValidationError
from geekvpn.domain.catalog.slug import validate_slug


class Category(AggregateRoot[uuid.UUID]):
    """A storefront grouping."""

    __slots__ = (
        "created_at",
        "description_fa",
        "icon",
        "name_en",
        "name_fa",
        "slug",
        "sort_order",
        "state",
    )

    def __init__(
        self,
        *,
        category_id: uuid.UUID,
        slug: str,
        name_fa: str,
        name_en: str | None = None,
        description_fa: str | None = None,
        icon: str | None = None,
        sort_order: int = 0,
        state: PublicationState = PublicationState.DRAFT,
        created_at: datetime | None = None,
    ) -> None:
        super().__init__(category_id)
        self.slug = validate_slug(slug, field="category slug")
        self.name_fa = _require_text(name_fa, field="name_fa", limit=64)
        self.name_en = name_en
        self.description_fa = description_fa
        self.icon = icon
        self.sort_order = sort_order
        self.state = state
        self.created_at = created_at

    @property
    def is_visible(self) -> bool:
        return self.state.is_visible

    def publish(self) -> None:
        self.state = PublicationState.PUBLISHED

    def archive(self) -> None:
        self.state = PublicationState.ARCHIVED


def _require_text(value: str, *, field: str, limit: int) -> str:
    text = (value or "").strip()
    if not text:
        raise CatalogValidationError(f"{field} is required.", field=field)
    if len(text) > limit:
        raise CatalogValidationError(
            f"{field} must be at most {limit} characters.",
            field=field,
            length=len(text),
        )
    return text
