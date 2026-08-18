"""The category -> product -> plan funnel, against the real DTOs.

Every one of these failed before the fix and the failure was invisible: the
handlers asked `match_ref` for `category_id`, `product_id` and `plan_id`, none
of which exist on the catalogue DTOs. `getattr` raised, so the whole revenue
path answered "this button is no longer valid" on the very first click, and no
test noticed because none of them used a real `CategoryView`.

So these build real DTOs and resolve real callback refs through the real
helper. A field renamed on either side breaks them.
"""

from __future__ import annotations

import uuid

import pytest

from geekvpn.application.catalog.dto import (
    CategoryView,
    PlanView,
    ProductView,
    QuoteView,
)
from geekvpn.presentation.bot.handlers.common import match_ref, short_ref


def make_plan(name: str = "یک‌ماهه") -> PlanView:
    plan_id = uuid.uuid4()
    return PlanView(
        id=plan_id,
        slug="monthly",
        name=name,
        plan_type="fixed",
        duration_days=30,
        quota_gib=50,
        daily_quota_gib=None,
        device_limit=2,
        description=None,
        badge=None,
        is_featured=False,
        price=QuoteView(
            plan_id=plan_id,
            product_id=uuid.uuid4(),
            base_price=250_000,
            total=250_000,
            total_discount=0,
            discount_percent=0,
            cashback=0,
            lines=(),
        ),
    )


def make_product(plans: tuple[PlanView, ...]) -> ProductView:
    return ProductView(
        id=uuid.uuid4(),
        slug="pro",
        tier="pro",
        name="حرفه‌ای",
        tagline=None,
        description=None,
        features=(),
        icon=None,
        badge=None,
        accent_color=None,
        is_featured=False,
        plans=plans,
    )


def make_category(products: tuple[ProductView, ...]) -> CategoryView:
    return CategoryView(
        id=uuid.uuid4(),
        slug="vpn",
        name="سرویس‌ها",
        description=None,
        icon=None,
        products=products,
    )


# -- the three hops the funnel makes --------------------------------------


def test_a_category_resolves_from_its_own_ref() -> None:
    category = make_category((make_product((make_plan(),)),))

    found = match_ref([category], short_ref(category.id), "id")

    assert found is category


def test_a_product_resolves_from_its_own_ref() -> None:
    product = make_product((make_plan(),))
    category = make_category((product,))

    found = match_ref(list(category.products), short_ref(product.id), "id")

    assert found is product


def test_a_plan_resolves_from_its_own_ref() -> None:
    plan = make_plan()
    product = make_product((plan,))

    found = match_ref(list(product.plans), short_ref(plan.id), "id")

    assert found is plan


def test_the_whole_funnel_walks_category_to_product_to_plan() -> None:
    """The exact traversal shop.py and purchase.py perform."""
    plan = make_plan()
    product = make_product((plan,))
    category = make_category((product,))
    categories = [make_category(()), category]

    hop1 = match_ref(categories, short_ref(category.id), "id")
    assert hop1 is not None
    hop2 = match_ref(list(hop1.products), short_ref(product.id), "id")
    assert hop2 is not None
    hop3 = match_ref(list(hop2.plans), short_ref(plan.id), "id")

    assert hop3 is plan


# -- the failure mode that hid the bug ------------------------------------


@pytest.mark.parametrize("attribute", ["category_id", "product_id", "plan_id"])
def test_asking_for_a_field_the_dto_does_not_have_is_loud(attribute: str) -> None:
    """These are the three names the handlers used to pass.

    A miss must look different from a typo. While `match_ref` merely raised
    per item, the funnel reported a stale button on every click and nothing
    said which field was wrong.
    """
    category = make_category((make_product((make_plan(),)),))

    with pytest.raises(AttributeError, match=attribute):
        match_ref([category], short_ref(category.id), attribute)


def test_a_genuine_miss_still_returns_none() -> None:
    """The stale-button path has to keep working; it is not an error."""
    category = make_category(())

    assert match_ref([category], "deadbeef", "id") is None


def test_an_empty_list_is_a_miss_not_a_crash() -> None:
    assert match_ref([], "deadbeef", "id") is None


# -- the plan label the review screen builds ------------------------------


def test_a_plan_exposes_name_not_name_fa() -> None:
    """purchase.py built its review title from `plan.name_fa`, which does not
    exist, so the review step raised after the plan had already been chosen."""
    plan = make_plan("سه‌ماهه")

    assert plan.name == "سه‌ماهه"
    assert not hasattr(plan, "name_fa")


# -- the real handlers, not just the helper -------------------------------
#
# The tests above pin `match_ref`. These pin the handlers, which is where the
# bug actually lived: `match_ref` was always correct, and the callers passed it
# a field name the DTO does not carry.


class Rendered:
    """Captures what the handler decided to show.

    `safe_edit` narrows on the real aiogram `Message`, so a stand-in is
    short-circuited before the handler's decision is visible. Capturing at that
    seam keeps the whole resolution path real - which is where the bug was -
    without pulling in aiogram's transport.
    """

    def __init__(self) -> None:
        self.bodies: list[str] = []

    async def capture(self, _query: object, body: str, **_kw: object) -> None:
        self.bodies.append(body)


class Storefront:
    def __init__(self, categories: tuple[CategoryView, ...]) -> None:
        self.categories = categories


async def _resolved(value: object) -> object:
    return value


async def drive(monkeypatch, handler_name: str, view: object, ref: str) -> Rendered:
    from geekvpn.presentation.bot.handlers import shop
    from geekvpn.presentation.bot.ui.callbacks import ShopCB

    rendered = Rendered()
    monkeypatch.setattr(shop, "load_storefront", lambda **_kw: _resolved(view))
    monkeypatch.setattr(shop, "safe_edit", rendered.capture)
    monkeypatch.setattr(shop, "toast", lambda *_a, **_kw: _resolved(None))

    await getattr(shop, handler_name)(
        object(),  # type: ignore[arg-type]
        ShopCB(action="cat", ref=ref),
        services=object(),  # type: ignore[arg-type]
        user=object(),
        scope=object(),
    )
    return rendered


async def test_clicking_a_category_lists_its_products(monkeypatch) -> None:
    """Before the fix this answered ERR_STALE_BUTTON for every category."""
    from geekvpn.presentation.bot.ui import text as T

    category = make_category((make_product((make_plan(),)),))
    view = Storefront((category,))

    rendered = await drive(monkeypatch, "on_category", view, short_ref(category.id))

    assert rendered.bodies, "the handler rendered nothing"
    assert T.ERR_STALE_BUTTON not in rendered.bodies[-1]
    assert category.name in rendered.bodies[-1]


async def test_clicking_a_product_lists_its_plans(monkeypatch) -> None:
    from geekvpn.presentation.bot.ui import text as T

    product = make_product((make_plan(),))
    view = Storefront((make_category((product,)),))

    rendered = await drive(monkeypatch, "on_product", view, short_ref(product.id))

    assert rendered.bodies
    assert T.ERR_STALE_BUTTON not in rendered.bodies[-1]


async def test_an_unknown_ref_still_reports_a_stale_button(monkeypatch) -> None:
    """The miss path must survive the fix; it is a real outcome, not an error."""
    from geekvpn.presentation.bot.ui import text as T

    view = Storefront((make_category((make_product((make_plan(),)),)),))

    rendered = await drive(monkeypatch, "on_category", view, "deadbeef")

    assert T.ERR_STALE_BUTTON in rendered.bodies[-1]
