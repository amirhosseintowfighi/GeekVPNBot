"""Auto-renew, rename and transfer, from the service's own screen."""

from __future__ import annotations

import uuid
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from geekvpn.application.bot.read_models import OwnerOptions, SubscriptionCard, SubscriptionState
from geekvpn.presentation.bot.handlers import dashboard, service_owner
from geekvpn.presentation.bot.handlers.common import short_ref
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import SubCB
from tests.unit.bot.test_app_password_handler import _State, _Typed

pytestmark = pytest.mark.unit

USER = SimpleNamespace(id=uuid.uuid4(), telegram_id=1001)
CARD = SubscriptionCard(
    subscription_id=uuid.uuid4(),
    plan_id=uuid.uuid4(),
    product_name_fa="آلمان",
    plan_name_fa="ماهانه",
    state=SubscriptionState.ACTIVE,
)
REF = short_ref(CARD.subscription_id)


class Subs:
    def __init__(self) -> None:
        self.card = CARD

    async def list_for_user(self, user_id: uuid.UUID) -> list[SubscriptionCard]:
        return [self.card]


class Ownership:
    def __init__(self, options: OwnerOptions | None = None) -> None:
        self._options = options or OwnerOptions(auto_renew=True, rename=True, transfer=True)
        self.transfers: list[int] = []
        self.missing: set[int] = set()

    async def options(self) -> OwnerOptions:
        return self._options

    async def set_auto_renew(self, user_id: Any, sid: Any, *, enabled: bool) -> SubscriptionCard:
        return replace(CARD, auto_renew=enabled)

    async def rename(self, user_id: Any, sid: Any, *, name: str | None) -> SubscriptionCard:
        return replace(CARD, display_name=name)

    async def transfer(self, user_id: Any, sid: Any, *, to_telegram_id: int) -> None:
        if to_telegram_id in self.missing:
            raise LookupError("nobody")
        self.transfers.append(to_telegram_id)


class Query:
    def __init__(self) -> None:
        self.message = None
        self.toasts: list[str | None] = []

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        self.toasts.append(text)


@pytest.fixture
def screens(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    shown: list[tuple[str, Any]] = []

    async def record(query: Any, body: str, *, markup: Any = None) -> None:
        shown.append((body, markup))

    monkeypatch.setattr(service_owner, "safe_edit", record)
    monkeypatch.setattr(dashboard, "safe_edit", record)
    return shown


def bundle(ownership: Ownership | None = None) -> Any:
    return SimpleNamespace(subscriptions=Subs(), ownership=ownership or Ownership())


def data(markup: Any) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_the_detail_screen_offers_each_control_the_shop_switched_on() -> None:
    markup = dashboard._detail_keyboard(
        CARD, OwnerOptions(auto_renew=True, rename=True, transfer=False)
    )

    assert SubCB(action="auto", ref=REF).pack() in data(markup)
    assert SubCB(action="rename", ref=REF).pack() in data(markup)
    assert SubCB(action="transfer", ref=REF).pack() not in data(markup)


async def test_the_auto_renew_button_flips_the_switch(screens: list[Any]) -> None:
    query = Query()

    await service_owner.on_auto_renew(query, SubCB(action="auto", ref=REF), bundle(), user=USER)  # type: ignore[arg-type]

    assert T.AUTO_RENEW_TURNED_ON in query.toasts
    body, _ = screens[-1]
    assert T.SUB_AUTO_RENEW_ON_LINE in body


async def test_a_new_name_is_taken_from_the_next_message() -> None:
    state = _State()
    await service_owner.on_rename_start(Query(), SubCB(action="rename", ref=REF), state)  # type: ignore[arg-type]
    typed = _Typed("گوشی مامان")

    await service_owner.on_rename_text(typed, state, bundle(), user=USER)  # type: ignore[arg-type]

    assert "گوشی مامان" in typed.replies[-1]
    assert state.state is None


async def test_a_transfer_waits_for_a_second_yes(screens: list[Any]) -> None:
    ownership = Ownership()
    services = bundle(ownership)
    state = _State()
    await service_owner.on_transfer_start(Query(), SubCB(action="transfer", ref=REF), state)  # type: ignore[arg-type]

    typed = _Typed("۲۰۰۲")
    await service_owner.on_transfer_target(typed, state, services, user=USER)  # type: ignore[arg-type]
    assert ownership.transfers == []
    assert "2002" in typed.replies[-1]

    await service_owner.on_transfer_confirm(
        Query(), SubCB(action="xfer_ok", ref=REF), state, services, user=USER  # type: ignore[arg-type]
    )
    assert ownership.transfers == [2002]
    assert screens[-1][0] == T.TRANSFER_DONE


async def test_a_transfer_to_nobody_says_so(screens: list[Any]) -> None:
    ownership = Ownership()
    ownership.missing.add(2002)
    services = bundle(ownership)
    state = _State()
    await state.update_data(owner_ref=REF, owner_to=2002)

    await service_owner.on_transfer_confirm(
        Query(), SubCB(action="xfer_ok", ref=REF), state, services, user=USER  # type: ignore[arg-type]
    )

    assert screens[-1][0] == T.TRANSFER_NO_SUCH_USER


async def test_giving_a_service_to_yourself_is_caught_before_the_confirmation() -> None:
    state = _State()
    await state.update_data(owner_ref=REF)
    typed = _Typed("1001")

    await service_owner.on_transfer_target(typed, state, bundle(), user=USER)  # type: ignore[arg-type]

    assert typed.replies == [T.TRANSFER_SELF]
