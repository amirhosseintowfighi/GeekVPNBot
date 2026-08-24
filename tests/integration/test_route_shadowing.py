"""A literal path declared after a parameterised one is unreachable.

FastAPI matches routes in declaration order. `GET /admin/payments/{payment_id}`
was declared before `GET /admin/payments/cards`, so the list of destination
cards was matched as a payment whose id is the word "cards" and answered "not
found" forever.

The symptom pointed anywhere but here: creating a card worked, because no
parameterised POST shadowed it; listing them returned nothing; and adding the
same card again reported that it already existed. That reads like a database
that saves but cannot read.
"""

from __future__ import annotations

import re

import pytest

from geekvpn.presentation.api.app import create_app

pytestmark = pytest.mark.integration

_PARAM = re.compile(r"\{[^}]+\}")


def _shadows(parameterised: str, literal: str) -> bool:
    """Would a request for `literal` be matched by `parameterised` first?

    A path parameter matches exactly one segment, so `/payments/{id}` swallows
    `/payments/cards` but leaves `/payments/cards/{id}` alone.
    """
    pattern = (
        "^"
        + "/".join(
            "[^/]+" if segment.startswith("{") else re.escape(segment)
            for segment in parameterised.split("/")
        )
        + "$"
    )
    return bool(re.match(pattern, literal))


def _walk(routes: object) -> list[object]:
    """Every leaf route, in declaration order.

    This FastAPI keeps an included router as a nested object rather than
    flattening it into `app.routes`, so a loop over the top level sees five
    routes and none of the ones that matter.
    """
    flat: list[object] = []
    for route in routes:  # type: ignore[attr-defined]
        included = getattr(route, "original_router", None)
        nested = getattr(included, "routes", None) or getattr(route, "routes", None)
        if nested:
            flat.extend(_walk(nested))
        else:
            flat.append(route)
    return flat


def test_no_literal_route_is_shadowed_by_an_earlier_parameterised_one() -> None:
    app = create_app()
    seen: list[tuple[str, frozenset[str]]] = []
    shadowed: list[str] = []

    for route in _walk(app.router.routes):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        if "{" not in path:
            for earlier, earlier_methods in seen:
                if "{" in earlier and _shadows(earlier, path) and earlier_methods & methods:
                    shadowed.append(f"{path} is unreachable behind {earlier}")
        seen.append((path, frozenset(methods)))

    assert not shadowed, "declare the literal path first:\n  " + "\n  ".join(shadowed)


def test_the_cards_list_is_reachable() -> None:
    """The one this file was written for."""
    spec = create_app().openapi()["paths"]

    assert "get" in spec["/api/v1/admin/payments/cards"]
