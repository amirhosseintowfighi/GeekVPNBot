"""The admin panel and the backend must agree on the URLs.

This whole class of bug - a front-end built against endpoints that were never
registered - is why the admin panel shipped unusable. A reviewer cannot catch it
by reading either side alone, so it is pinned here instead.

The test extracts the paths `admin/src` actually calls, normalises them, and
compares them with the routes `create_app()` registers. `KNOWN_GAPS` is the
explicit list of calls with no backend yet: it must only ever shrink, and the
test fails both when a *new* mismatch appears and when a listed gap is quietly
fixed without being removed here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from geekvpn.presentation.api.app import API_V1_PREFIX, create_app

pytestmark = pytest.mark.integration

ADMIN_SRC = Path(__file__).resolve().parents[2] / "admin" / "src"

#: Endpoints the admin panel calls that the backend does not serve yet.
#:
#: Empty, and meant to stay that way. Every entry it once held is closed: three
#: were routes the products screen calls and nobody had registered, and the rest
#: were stale - listed as missing long after the client had stopped calling them
#: at all, which is why the list is now checked from both directions.
KNOWN_GAPS: frozenset[str] = frozenset()

#: A `${...}` interpolation, tolerating one level of nesting so that
#: `${encodeURIComponent(key)}` collapses to a single segment rather than
#: truncating the path at the first bracket.
_TEMPLATE = re.compile(r"\$\{(?:[^{}]|\{[^{}]*\})*\}")


def called_paths() -> set[str]:
    """Every `${ROOT}/...` template literal the admin client builds."""
    found: set[str] = set()
    for file in ADMIN_SRC.rglob("*.ts"):
        # Up to the closing backtick, not to the first bracket: a path can
        # contain a call, as `${encodeURIComponent(key)}` does.
        for raw in re.findall(r"`(\$\{ROOT\}/[^`]*)`", file.read_text(encoding="utf-8")):
            # A trailing `${qs(...)}` is a query string, not a path segment.
            path = raw.split("${qs")[0]
            # Expand ${ROOT} before collapsing the rest, or the prefix itself
            # becomes an {id} segment.
            path = path.replace("${ROOT}", f"{API_V1_PREFIX}/admin")
            found.add(_TEMPLATE.sub("{id}", path).rstrip("/"))
    return found


def client_calls() -> set[tuple[str, str]]:
    """Every `mutate('VERB', `${ROOT}/...`)` the client makes, as (verb, path).

    Read-only calls go through `fetcher`, which is GET by construction, so only
    the mutations can disagree about the verb.
    """
    pattern = re.compile(r"mutate<[^>]*>\(\s*'(POST|PUT|PATCH|DELETE)',\s*`([^`]+)`")
    found: set[tuple[str, str]] = set()
    for file in ADMIN_SRC.rglob("*.ts"):
        for method, raw in pattern.findall(file.read_text(encoding="utf-8")):
            path = raw.split("${qs")[0].replace("${ROOT}", f"{API_V1_PREFIX}/admin")
            found.add((method, _TEMPLATE.sub("{id}", path).rstrip("/")))
    return found


def registered_paths() -> set[str]:
    """Registered routes with their parameter names normalised away."""
    return {
        _TEMPLATE.sub("{id}", re.sub(r"\{[^}]*\}", "{id}", path))
        for path in create_app().openapi()["paths"]
    }


def test_the_admin_client_is_actually_reading_from_a_real_directory() -> None:
    """Guards the test itself: a bad path would make everything below vacuous."""
    assert ADMIN_SRC.is_dir()
    assert called_paths()


def test_every_endpoint_the_admin_panel_calls_is_registered() -> None:
    missing = called_paths() - registered_paths() - KNOWN_GAPS
    assert not missing, (
        "The admin panel calls endpoints the backend does not serve:\n  "
        + "\n  ".join(sorted(missing))
        + "\nEither register the route or add it to KNOWN_GAPS with a reason."
    )


def test_no_known_gap_has_been_quietly_closed() -> None:
    """Keeps the gap list honest.

    A gap that got implemented but stayed listed would hide the next real
    regression behind a stale exemption.
    """
    closed = KNOWN_GAPS & registered_paths()
    assert not closed, (
        "These are now registered and must be removed from KNOWN_GAPS:\n  "
        + "\n  ".join(sorted(closed))
    )


def test_no_gap_is_listed_that_the_panel_no_longer_calls() -> None:
    """A gap list only shrinks if a dead entry cannot hide in it.

    Six entries here outlived the calls that justified them, which made the
    list read as six missing features when the real number was three.
    """
    stale = KNOWN_GAPS - called_paths()
    assert not stale, "The admin panel no longer calls these, so they are not gaps: " + ", ".join(
        sorted(stale)
    )


def test_the_ladder_endpoints_are_registered_where_the_panel_calls_them() -> None:
    """The products screen builds three calls that had no route behind them.

    `DurationLadderService` was a finished service with tests and no caller -
    nothing outside its own test file ever constructed it - so an operator
    clicking "generate ladder" got a 404 and no packages.
    """
    registered = registered_paths()

    assert f"{API_V1_PREFIX}/admin/duration-ladder" in registered
    assert f"{API_V1_PREFIX}/admin/catalog/plans/generate-ladder" in registered
    assert f"{API_V1_PREFIX}/admin/catalog/products/{{id}}/plans" in registered


def test_the_ladder_dialog_can_build_every_plan_type_the_domain_has() -> None:
    """A catalogue that can only sell time is half a catalogue.

    The dialog hardcoded `unlimited` and asked for no volume, so `PlanType`
    had three members and the panel could reach one. The quota rule it must
    respect is `Plan._validate_quotas`: exactly one field, chosen by type.
    """
    from geekvpn.domain.catalog.enums import PlanType

    source = (ADMIN_SRC / "lib" / "plans.ts").read_text(encoding="utf-8")

    for plan_type in PlanType:
        assert f"'{plan_type.value}'" in source, (
            f"the admin panel cannot build a {plan_type.value} package"
        )


def test_the_panel_calls_every_route_with_the_method_it_declares() -> None:
    """A path that exists is not a route that answers.

    `KNOWN_GAPS` compares paths and nothing else, so the panel could call a
    real path with the wrong verb and this file stayed green. Publishing a
    package did exactly that: the route is PUT and the client sent POST, so
    every attempt answered 405 and the operator could not put anything on
    sale.
    """
    spec = create_app().openapi()["paths"]
    by_path: dict[str, set[str]] = {
        _TEMPLATE.sub("{id}", re.sub(r"\{[^}]*\}", "{id}", path)): {
            method.upper() for method in operations
        }
        for path, operations in spec.items()
    }

    mismatches: list[str] = []
    for method, path in client_calls():
        allowed = by_path.get(path)
        if allowed is None:
            continue  # a missing path is the other test's job
        if method not in allowed:
            mismatches.append(f"{method} {path} (route accepts {', '.join(sorted(allowed))})")

    assert not mismatches, "the admin panel uses a verb the route refuses:\n  " + "\n  ".join(
        sorted(mismatches)
    )


def test_the_panel_sends_the_state_verbs_the_campaign_route_accepts() -> None:
    """A method check cannot see this one: right path, right verb, wrong words.

    `/campaigns/{id}/state` takes activate, pause or archive. The screen sent
    "published" and "draft" - the vocabulary the *other* state routes use - and
    the campaign switch failed on every flick.
    """
    import re as _re

    from geekvpn.presentation.api.schemas_catalog import CampaignStateRequest

    field = CampaignStateRequest.model_fields["state"]
    pattern = next(m.pattern for m in field.metadata if hasattr(m, "pattern"))
    accepted = set(_re.findall(r"[a-z]+", pattern))

    source = (ADMIN_SRC / "lib" / "api.ts").read_text(encoding="utf-8")
    signature = source[source.index("setCampaignState") : source.index("setCampaignState") + 400]
    offered = set(_re.findall(r"'([a-z]+)'", signature)) - {"put"}

    assert offered <= accepted, (
        f"the panel offers campaign states the route rejects: {sorted(offered - accepted)}"
    )


def test_the_panel_can_walk_the_whole_chain_from_node_to_published_package() -> None:
    """Selling anything requires five links, and any one missing stops it.

    A node, a category, a product, that product bound to the node, and a
    package published under it. `Product.publish` refuses an unbound product
    and `set_plan_state` refuses a package under an unpublished one, so a
    single missing button leaves the catalogue permanently in draft - which is
    exactly what happened: `bindProductPanel` and `setProductState` both
    existed in the client with no screen calling either.
    """
    source = (ADMIN_SRC / "app" / "products" / "page.tsx").read_text(encoding="utf-8")
    client = (ADMIN_SRC / "lib" / "api.ts").read_text(encoding="utf-8")

    for call in ("bindProductPanel", "setProductState", "generateLadder", "setPlanState"):
        assert f"api.{call}(" in source or f"{call}(" in source, (
            f"the products screen never calls {call}, so the chain stops there"
        )
        assert f"{call}:" in client, f"{call} is missing from the client"
