"""The review screen must only read fields the storefront actually hands it.

`_render_review` built its title from `plan.name_fa`. `PlanView` has `name`;
`name_fa` belongs to the catalogue model and to `ServerStatusRow`, which is how
the same mistake got written twice. Every customer who picked a package got the
generic apology, and mypy could not see it because the handler took the plan as
`Any`.

The lookup is typed now, so this class of typo fails the type check rather than
the customer. These assertions pin the field names themselves, for the same
reason the type annotation exists: the two must not drift apart quietly.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from geekvpn.application.catalog.dto import PlanView, ProductView

pytestmark = pytest.mark.unit

HANDLER = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "geekvpn"
    / "presentation"
    / "bot"
    / "handlers"
    / "purchase.py"
)


def test_a_plan_carries_a_name_and_not_a_name_fa() -> None:
    assert "name" in PlanView.__annotations__
    assert "name_fa" not in PlanView.__annotations__


def _attributes_read_from(variable: str) -> set[str]:
    """Attribute names the module reads off `variable`, from the syntax tree.

    Parsed rather than grepped: both this file and the handler discuss the very
    field name the test is about, and a regex cannot tell a sentence in a
    docstring from a line that runs.
    """
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"))
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == variable
    }


def test_the_review_screen_reads_only_fields_a_plan_has() -> None:
    unknown = _attributes_read_from("plan") - set(PlanView.__annotations__)

    assert not unknown, f"the purchase flow reads fields PlanView does not have: {sorted(unknown)}"


def test_the_review_screen_reads_only_fields_a_product_has() -> None:
    unknown = _attributes_read_from("product") - set(ProductView.__annotations__)
    assert not unknown, (
        f"the purchase flow reads fields ProductView does not have: {sorted(unknown)}"
    )


def test_the_lookup_is_typed_so_the_checker_can_see_the_next_one() -> None:
    """An `Any` here is what let the mistake reach a customer."""
    source = HANDLER.read_text(encoding="utf-8")

    assert "tuple[PlanView | None, ProductView | None]" in source
