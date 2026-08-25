"""The Mini App reads what the API sends, or it renders nothing at all.

`/storefront` returned the internal `StorefrontView` dataclass, typed `Any`.
FastAPI serialised it field for field, so the payload arrived with the domain's
own names in snake_case - `id`, `name`, `tagline` - while the Mini App reads
`categoryId`, `nameFa`, `taglineFa`. Every field was undefined, mapping over
`products` threw, and the storefront rendered as "a client-side exception has
occurred", which says nothing about which field was missing.

A response model fixes the payload. This pins it to the TypeScript the Mini App
actually reads, because the two live in different languages and nothing else
compares them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from geekvpn.presentation.api.routers.miniapp import (
    CategoryCard,
    PlanCard,
    ProductCard,
    StorefrontResponse,
)

pytestmark = pytest.mark.integration

TYPES = Path(__file__).resolve().parents[2] / "miniapp" / "src" / "lib" / "types.ts"


def _fields_of(interface: str) -> set[str]:
    """The property names of one TypeScript interface."""
    source = TYPES.read_text(encoding="utf-8")
    match = re.search(rf"export interface {interface} \{{(.*?)\n\}}", source, re.DOTALL)
    assert match, f"{interface} is gone from the Mini App's types"
    return set(re.findall(r"^\s*(\w+)[?]?:", match.group(1), re.MULTILINE))


def _sent_by(model: type) -> set[str]:
    """The names the API actually puts on the wire, which are the aliases."""
    return {
        (field.alias or name) for name, field in model.model_fields.items()
    }


@pytest.mark.parametrize(
    ("model", "interface"),
    [
        (StorefrontResponse, "Storefront"),
        (CategoryCard, "CategoryCard"),
        (ProductCard, "ProductCard"),
        (PlanCard, "PlanCard"),
    ],
)
def test_the_mini_app_reads_only_fields_the_api_sends(model: type, interface: str) -> None:
    missing = _fields_of(interface) - _sent_by(model)

    assert not missing, (
        f"{interface} reads fields /storefront never sends: {sorted(missing)}"
    )


def test_the_payload_is_camel_case() -> None:
    """snake_case is what the crash looked like: every read undefined."""
    sent = _sent_by(PlanCard)

    assert "planId" in sent
    assert "plan_id" not in sent
