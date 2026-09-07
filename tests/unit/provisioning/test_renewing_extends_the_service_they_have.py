"""Renewal, which until now was a second purchase wearing a renewal button.

`Order.is_renewal` and `Order.renews_subscription_id` have existed since the
first release and nothing ever set them, so `ProvisioningService._renew` - the
half that extends the account the customer already installed - was unreachable.
Pressing "renew" placed an ordinary order and provisioned a *new* panel account
with new config, which is the one thing renewal exists to avoid.

Two more things it could not do, both reported from production:

* an adopted service (claimed from a pasted link) has no plan behind it by
  design, and the screen looked that plan up to decide what to offer - so it
  offered nothing at all;
* a 20GB customer who wanted 100GB was shown only their own product's plans.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from geekvpn.domain.provisioning.enums import SubscriptionState
from geekvpn.domain.provisioning.subscription import Subscription
from geekvpn.infrastructure.bot.checkout import BotCheckoutAdapter
from geekvpn.presentation.bot.handlers.renewal import _upgrade_keyboard
from geekvpn.presentation.bot.ui import text as T

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 8, tzinfo=UTC)


# -- what the screen offers ------------------------------------------------


def _plan(*, gib: int, price: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        quota_gib=gib,
        duration_days=30,
        device_limit=2,
        is_featured=False,
        price=SimpleNamespace(total=price, campaign_label=None),
    )


def _view(*products: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(categories=[SimpleNamespace(products=list(products))])


def _labels(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def test_a_service_whose_package_was_retired_can_still_be_renewed() -> None:
    """The old screen found the product by looking the plan up, and answered
    "this package no longer exists" when it could not - which is precisely the
    customer who most needs to renew onto something else."""
    gone = uuid.uuid4()
    product = SimpleNamespace(
        id=uuid.uuid4(), name="گیک توربو", plans=[_plan(gib=100, price=250_000)]
    )

    labels = _labels(_upgrade_keyboard(_view(product), same_plan_id=gone, own_product_id=None))

    # One package button, plus the back row - not the dead end it used to be.
    assert any(product.name in label for label in labels)


def test_an_upgrade_to_another_product_is_on_the_same_screen() -> None:
    """20GB to 100GB. The list was scoped to the product the subscription was
    sold on, so the only upgrades offered were the ones inside it."""
    mine = SimpleNamespace(id=uuid.uuid4(), name="گیک ساده", plans=[_plan(gib=20, price=100_000)])
    other = SimpleNamespace(
        id=uuid.uuid4(), name="گیک توربو", plans=[_plan(gib=100, price=250_000)]
    )

    labels = _labels(
        _upgrade_keyboard(
            _view(mine, other), same_plan_id=mine.plans[0].id, own_product_id=mine.id
        )
    )

    # The other product is offered, and named - a button reads
    # "price - volume - duration" and nothing else, so without the product
    # name there is no telling the families apart.
    assert any(other.name in label for label in labels)
    # Their own package is first and marked as the same one.
    assert labels[0].startswith(T.RENEW_SAME_PLAN)


# -- who may be renewed ----------------------------------------------------


class _Bridge:
    async def telegram_id(self, user_id: uuid.UUID) -> int:
        return 555

    async def run(self, work):  # pragma: no cover - the guard fires first
        raise AssertionError("A refused renewal must not reach the payment scope.")


class _Plans:
    async def get(self, plan_id: uuid.UUID):
        return SimpleNamespace(
            name_fa="سه ماهه", duration_days=90, quota_gib=100, device_limit=2
        )


class _Subscriptions:
    def __init__(self, owner: int) -> None:
        self._owner = owner

    async def get(self, subscription_id: str):
        return SimpleNamespace(id=subscription_id, user_id=self._owner)


def _adapter(owner: int) -> BotCheckoutAdapter:
    return BotCheckoutAdapter(  # type: ignore[arg-type]
        bridge=_Bridge(),
        quoting=object(),
        orders=object(),
        order_repository=object(),
        provisioning=object(),
        session=object(),
        plans=_Plans(),
        coupons=object(),
        subscriptions=_Subscriptions(owner),
        clock=object(),
        jalali_year=1405,
    )


async def test_nobody_can_renew_a_stranger_s_service() -> None:
    """The id travels in a callback and a request body, and a renewal writes an
    absolute quota - so an unchecked one lets anybody pay for a 20GB renewal
    onto someone else's 100GB service and shrink it."""
    with pytest.raises(LookupError):
        await _adapter(owner=999).begin_card(
            uuid.uuid4(), plan_id=uuid.uuid4(), renews_subscription_id="not-theirs"
        )


# -- what a renewal does to the service ------------------------------------


def _subscription() -> Subscription:
    return Subscription(
        "sub-1",
        user_id=555,
        order_id="order-old",
        plan_id="plan-20gb",
        started_at=NOW - timedelta(days=30),
        expires_at=NOW + timedelta(days=2),
        remote_username="amir",
        state=SubscriptionState.ACTIVE,
        node_id="node-1",
        traffic_limit_mib=20 * 1024,
        traffic_used_mib=19 * 1024,
    )


def test_renewing_onto_a_bigger_package_moves_the_service_to_it() -> None:
    """Not only the quota. Every screen reads the package name through the
    order, so a subscription left pointing at the old one showed the customer
    100GB of allowance under the name of the 20GB plan they had left behind."""
    subscription = _subscription()

    subscription.renew(
        days=30,
        now=NOW,
        quota_mib=100 * 1024,
        plan_id="plan-100gb",
        order_id="order-new",
    )

    assert subscription.plan_id == "plan-100gb"
    assert subscription.order_id == "order-new"
    assert subscription.traffic_limit_mib == 100 * 1024
    assert subscription.traffic_used_mib == 0
    # Extended from the existing expiry, so renewing early costs nothing.
    assert subscription.expires_at == NOW + timedelta(days=32)


def test_the_account_itself_is_untouched_by_a_renewal() -> None:
    """The reason renewal exists: same panel account, same link, nothing for
    the customer to install again."""
    subscription = _subscription()
    before = (subscription.remote_username, subscription.node_id, subscription.id)

    subscription.renew(days=30, now=NOW, quota_mib=100 * 1024, plan_id="plan-100gb")

    assert (subscription.remote_username, subscription.node_id, subscription.id) == before
