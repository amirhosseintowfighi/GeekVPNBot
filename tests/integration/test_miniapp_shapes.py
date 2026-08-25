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
from pydantic.alias_generators import to_camel, to_snake

from geekvpn.application.bot import read_models
from geekvpn.presentation.api.routers import miniapp
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


# -- endpoints without a response model -------------------------------------
#
# Most Mini App endpoints return an application read model directly. Those are
# flat DTOs shaped for exactly these screens, so a response model per endpoint
# would only restate them - `_CamelCaseRoute` fixes the one thing that was
# wrong on the wire, which was the spelling. The check below is what keeps the
# two sides honest instead.
#
# The failure this catches has a signature: the services card read `usedGib`,
# `quotaGib` and `deviceLimit` off a payload spelling them `used_gib`,
# `quota_gib`, `device_limit`, and rendered "NaN گیگابایت از NaN گیگابایت".


def _sent_by_dataclass(model: type) -> set[str]:
    return {to_camel(name) for name in model.__dataclass_fields__}


#: Fields the endpoint composes on top of its read model, and where from. A
#: read model is one query's worth of data; these are facts that live in
#: another one, and joining them in the reader would mean reaching across the
#: sync/async boundary for a screen's convenience.
COMPOSED: dict[str, set[str]] = {
    # Lifetime spend is a wallet fact, so the tier derived from it is too.
    "ProfileSummary": {"tier", "lifetimeSpend"},
    # The invite terms are admin-configurable settings, not the customer's own
    # results, and the invite screen has to quote them.
    "ReferralSummary": {"inviteeBonus", "firstPurchaseBps", "recurringBps"},
    # The destination card comes from the gateway registry: it rotates, and a
    # customer mid-transfer must see the one that is active now.
    "PendingPayment": {"card", "crypto"},
}


@pytest.mark.parametrize(
    ("model", "interface"),
    [
        (read_models.SubscriptionCard, "SubscriptionCard"),
        (read_models.WalletSnapshot, "WalletSnapshot"),
        (read_models.WalletTransaction, "WalletTransaction"),
        (read_models.ReferralSummary, "ReferralSummary"),
        (read_models.ProfileSummary, "ProfileSummary"),
        (read_models.ServerStatusRow, "ServerStatusRow"),
        (read_models.TicketCard, "TicketCard"),
        (read_models.PendingPayment, "PendingPayment"),
    ],
)
def test_the_mini_app_reads_only_fields_the_read_model_carries(
    model: type, interface: str
) -> None:
    sent = _sent_by_dataclass(model) | COMPOSED.get(interface, set())
    missing = _fields_of(interface) - sent

    assert not missing, (
        f"{interface} reads fields {model.__name__} does not carry: {sorted(missing)}"
    )


def test_the_router_camel_cases_what_it_sends() -> None:
    """Without this every field above arrives under its Python name."""
    assert miniapp.router.route_class is miniapp._CamelCaseRoute
    assert miniapp._camelize({"used_gib": [{"quota_gib": 1}]}) == {
        "usedGib": [{"quotaGib": 1}]
    }


def test_every_composed_field_is_actually_composed_somewhere() -> None:
    """`COMPOSED` is a claim about the router, so it is checked against it.

    Otherwise the list above becomes a place to silence this test: name a field
    here and the check passes whether or not anything sends it.
    """
    source = Path(miniapp.__file__).read_text(encoding="utf-8")
    unsent = [
        name
        for names in COMPOSED.values()
        for name in names
        if f'"{to_snake(name)}"' not in source
    ]

    assert not unsent, f"claimed to be composed by the router, but never sent: {unsent}"


def test_the_thread_says_which_side_each_message_is() -> None:
    """The Mini App draws two sides of a conversation from one boolean.

    It was never sent one, so every message rendered as the customer's -
    including the answers they had come to read.
    """
    import ast
    from pathlib import Path

    source = Path(miniapp.__file__).read_text(encoding="utf-8")
    view = next(
        ast.unparse(node)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_message_view"
    )

    assert "'from_support'" in view or '"from_support"' in view
