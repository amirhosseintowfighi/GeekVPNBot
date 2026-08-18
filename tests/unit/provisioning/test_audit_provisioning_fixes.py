"""Provisioning defects the audit found.

The renewal quota mismatch is the one worth reading twice: no test ever passed
``extra_mib``, so the entire quota half of renewal was uncovered while the date
half was tested three times over.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.domain.provisioning.enums import OrderState, SubscriptionState
from geekvpn.domain.provisioning.subscription import Subscription

NOW = datetime(2026, 8, 19, tzinfo=UTC)
GIB = 1024


def make_subscription(*, used: int = 0, limit: int | None = 50 * GIB) -> Subscription:
    return Subscription(
        "sub-1",
        user_id=555,
        order_id="ord-1",
        plan_id="plan-1",
        state=SubscriptionState.ACTIVE,
        node_id="fra",
        remote_username="u1",
        started_at=NOW - timedelta(days=30),
        expires_at=NOW + timedelta(days=1),
        traffic_limit_mib=limit,
        traffic_used_mib=used,
        device_limit=2,
    )


# -- 16: the renewal quota ------------------------------------------------


def test_renewing_sets_the_allowance_rather_than_adding_to_it() -> None:
    """The panel is given an absolute figure. A domain that accumulated drifted
    one term further from it on every renewal."""
    sub = make_subscription()

    sub.renew(days=30, now=NOW, quota_mib=50 * GIB)
    sub.renew(days=30, now=NOW, quota_mib=50 * GIB)

    assert sub.traffic_limit_mib == 50 * GIB


def test_renewing_resets_the_usage_it_is_measured_against() -> None:
    """A fresh allowance against a carried-over counter would leave a customer
    exhausted the moment they renewed."""
    sub = make_subscription(used=48 * GIB)

    sub.renew(days=30, now=NOW, quota_mib=50 * GIB)

    assert sub.traffic_used_mib == 0


def test_an_exhausted_subscription_becomes_active_again_on_renewal() -> None:
    sub = make_subscription(used=50 * GIB)
    sub.record_usage(used_mib=50 * GIB, at=NOW)

    sub.renew(days=30, now=NOW, quota_mib=50 * GIB)

    assert sub.state is SubscriptionState.ACTIVE


def test_renewing_without_a_quota_leaves_the_allowance_alone() -> None:
    """An unlimited plan passes None, and must not be silently given zero."""
    sub = make_subscription(used=10 * GIB, limit=None)

    sub.renew(days=30, now=NOW, quota_mib=None)

    assert sub.traffic_limit_mib is None
    assert sub.traffic_used_mib == 10 * GIB


def test_renewing_early_keeps_the_days_already_paid_for() -> None:
    """Unchanged by the quota fix, and worth keeping honest."""
    sub = make_subscription()
    expiry = sub.expires_at

    sub.renew(days=30, now=NOW, quota_mib=50 * GIB)

    assert sub.expires_at == expiry + timedelta(days=30)


def test_the_service_sends_the_same_figure_to_both_sides() -> None:
    from geekvpn.application.provisioning.provisioning_service import ProvisioningService

    source = inspect.getsource(ProvisioningService._renew)

    assert "quota_mib=order.traffic_mib" in source
    assert "new_quota=_quota_for(order.traffic_mib)" in source
    assert "RESET_TRAFFIC" in source, "the panel counter is never cleared"


# -- 15: orders stuck mid-provision ---------------------------------------


def test_provisioning_is_a_retryable_state() -> None:
    """start_provisioning commits before the panel call, so a worker killed
    between the two leaves an order there permanently."""
    from geekvpn.infrastructure.persistence.repositories.provisioning import _RETRYABLE

    assert OrderState.PROVISIONING.value in _RETRYABLE
    assert OrderState.PAID.value in _RETRYABLE
    assert OrderState.FAILED.value in _RETRYABLE


def test_a_second_attempt_does_not_re_enter_the_state() -> None:
    """Re-entering PROVISIONING is an illegal transition, and refusing the
    retry is what made those orders unrecoverable."""
    from geekvpn.application.provisioning.provisioning_service import ProvisioningService

    source = inspect.getsource(ProvisioningService.provision)

    assert "if order.state is not OrderState.PROVISIONING:" in source


def test_one_bad_order_cannot_abort_the_sweep() -> None:
    """A listed exception tuple is a promise that nothing else can be raised;
    an IllegalOrderTransition from one row used to end the whole batch."""
    from geekvpn.application.provisioning.provisioning_service import ProvisioningService

    source = inspect.getsource(ProvisioningService.drain_stuck)

    assert "except Exception:" in source
    assert "continue" in source


# -- 18: one order, one subscription --------------------------------------


def test_the_order_row_is_locked_before_the_existence_check() -> None:
    from geekvpn.application.provisioning.provisioning_service import ProvisioningService

    source = inspect.getsource(ProvisioningService.provision)

    assert "get_for_update(order_id)" in source
    assert source.index("get_for_update(") < source.index("get_by_order(")


def test_the_model_declares_the_unique_constraint() -> None:
    from geekvpn.infrastructure.persistence.models.provisioning import SubscriptionModel

    names = {
        constraint.name for constraint in SubscriptionModel.__table__.constraints if constraint.name
    }

    assert "uq_subscriptions_order" in names


def test_a_migration_adds_the_constraint() -> None:
    """The model and the schema must agree; a constraint only in the model is
    a constraint that does not exist."""
    from pathlib import Path

    migrations = Path("migrations/versions").glob("*.py")
    assert any("uq_subscriptions_order" in path.read_text(encoding="utf-8") for path in migrations)


# -- 19: the expiry sweep --------------------------------------------------


def test_the_service_exposes_an_expiry_sweep() -> None:
    """list_lapsed and Subscription.expire both existed with no callers, so a
    lapsed service stayed ACTIVE forever and never prompted a renewal."""
    from geekvpn.application.provisioning.provisioning_service import ProvisioningService

    assert hasattr(ProvisioningService, "expire_lapsed")
    source = inspect.getsource(ProvisioningService.expire_lapsed)
    assert "list_lapsed(" in source
    assert ".expire(" in source


def test_the_worker_runs_the_sweep() -> None:
    """Written but unregistered is the same dead code with a new name."""
    from geekvpn.entrypoints import worker

    source = inspect.getsource(worker)

    assert "expire_lapsed()" in source
    assert "run_expiry_sweep" in source
    assert "EXPIRY_SWEEP_INTERVAL_SECONDS" in source


def test_one_stubborn_subscription_cannot_abort_the_sweep() -> None:
    from geekvpn.application.provisioning.provisioning_service import ProvisioningService

    assert "continue" in inspect.getsource(ProvisioningService.expire_lapsed)


# -- 17: the 409 retry on unlimited plans ---------------------------------


@pytest.mark.parametrize("adapter", ["marzban", "marzneshin", "pasarguard"])
def test_the_conflict_retry_normalises_both_quotas(adapter: str) -> None:
    """Unlimited is None on one side and 0 on the other, so `None == 0` made
    the retry fail for exactly the case where it is guaranteed correct."""
    from pathlib import Path

    source = Path(f"src/geekvpn/infrastructure/panels/adapters/{adapter}.py").read_text(
        encoding="utf-8"
    )

    assert "(existing.usage.quota.total_bytes or 0) == (spec.quota.total_bytes or 0)" in source
    assert "existing.usage.quota.total_bytes == (" not in source


def test_none_and_zero_really_do_differ() -> None:
    """The property the bug rested on, stated once so the fix is not mysterious."""
    assert None != 0
    assert (None or 0) == (None or 0)
