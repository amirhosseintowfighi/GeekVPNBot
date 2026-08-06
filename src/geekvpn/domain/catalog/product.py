"""Products: the branded tiers a customer chooses between.

A product is *not* something you can buy. You buy a `Plan`. The product is the
brand and the promise - "Geek Turbo, low ping, tunnelled" - and it owns the
marketing copy plus the technical binding that tells provisioning which panel
and which nodes to use.

Separating the two is what lets marketing rewrite every word of a product page
without touching a single price, and lets finance reprice every package without
touching a single word of copy.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from geekvpn.domain.base.entity import AggregateRoot
from geekvpn.domain.catalog.enums import ProductTier, PublicationState
from geekvpn.domain.catalog.errors import CatalogValidationError
from geekvpn.domain.catalog.slug import validate_slug

MAX_FEATURES = 12


class Product(AggregateRoot[uuid.UUID]):
    """A branded tier such as Geek Direct, Geek Turbo or Geek Elite."""

    __slots__ = (
        "accent_color",
        "badge_fa",
        "category_id",
        "created_at",
        "description_fa",
        "features_fa",
        "icon",
        "is_featured",
        "name_fa",
        "node_tags",
        "panel_id",
        "slug",
        "sort_order",
        "state",
        "tagline_fa",
        "tier",
    )

    def __init__(
        self,
        *,
        product_id: uuid.UUID,
        category_id: uuid.UUID,
        slug: str,
        tier: ProductTier,
        name_fa: str,
        tagline_fa: str | None = None,
        description_fa: str | None = None,
        features_fa: tuple[str, ...] = (),
        icon: str | None = None,
        badge_fa: str | None = None,
        accent_color: str | None = None,
        sort_order: int = 0,
        state: PublicationState = PublicationState.DRAFT,
        panel_id: uuid.UUID | None = None,
        node_tags: tuple[str, ...] = (),
        is_featured: bool = False,
        created_at: datetime | None = None,
    ) -> None:
        super().__init__(product_id)
        self.category_id = category_id
        self.slug = validate_slug(slug, field="product slug")
        self.tier = tier
        self.name_fa = _require_text(name_fa, field="name_fa", limit=64)
        self.tagline_fa = tagline_fa
        self.description_fa = description_fa
        self.features_fa = _validate_features(features_fa)
        self.icon = icon
        self.badge_fa = badge_fa
        self.accent_color = accent_color
        self.sort_order = sort_order
        self.state = state
        self.panel_id = panel_id
        self.node_tags = node_tags
        self.is_featured = is_featured
        self.created_at = created_at

    @property
    def is_visible(self) -> bool:
        return self.state.is_visible

    @property
    def is_provisionable(self) -> bool:
        """Whether an order for this product could actually be fulfilled.

        A published product with no panel binding is a trap: the customer pays
        and provisioning has nowhere to send them. `publish()` refuses it.
        """
        return self.panel_id is not None

    def publish(self) -> None:
        if not self.is_provisionable:
            raise CatalogValidationError(
                "A product cannot be published before it is bound to a panel.",
                product_id=str(self.id),
                slug=self.slug,
            )
        self.state = PublicationState.PUBLISHED

    def archive(self) -> None:
        self.state = PublicationState.ARCHIVED

    def bind_panel(self, panel_id: uuid.UUID, *, node_tags: tuple[str, ...] = ()) -> None:
        self.panel_id = panel_id
        self.node_tags = node_tags


def _validate_features(features: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = tuple(f.strip() for f in features if f and f.strip())
    if len(cleaned) > MAX_FEATURES:
        raise CatalogValidationError(
            f"A product may list at most {MAX_FEATURES} features.",
            count=len(cleaned),
        )
    return cleaned


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
