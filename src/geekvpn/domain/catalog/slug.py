"""Slug validation.

Slugs appear in deep links (`t.me/GeekVPNBot?start=buy_geek-turbo-1m`) and in
admin URLs, so they must be URL-safe, stable and human-readable. Generating them
from Persian names automatically produces either transliteration mush or
percent-encoded noise, so operators choose them explicitly and we validate.
"""

from __future__ import annotations

import re
from typing import Final

from geekvpn.domain.catalog.errors import CatalogValidationError

SLUG_PATTERN: Final = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_SLUG_LENGTH: Final = 64


def validate_slug(value: str, *, field: str = "slug") -> str:
    """Return the normalised slug or raise.

    Lowercased before validation so that an operator typing `Geek-Turbo` gets a
    working slug rather than a rejection. Everything else is strict: underscores
    and trailing hyphens are rejected rather than silently rewritten, because a
    slug that does not match what was typed is confusing in an audit log.
    """
    text = (value or "").strip().lower()
    if not text:
        raise CatalogValidationError(f"{field} is required.", field=field)
    if len(text) > MAX_SLUG_LENGTH:
        raise CatalogValidationError(
            f"{field} must be at most {MAX_SLUG_LENGTH} characters.",
            field=field,
            length=len(text),
        )
    if not SLUG_PATTERN.match(text):
        raise CatalogValidationError(
            f"{field} may contain only lowercase letters, digits and single hyphens.",
            field=field,
            value=text,
        )
    return text
