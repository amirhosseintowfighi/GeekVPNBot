"""The free trial, claimed from inside the bot.

It existed only in the Android app and the Mini App, so a customer who never
left Telegram - most of them - had no way to try before paying.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from geekvpn.application.bot.read_models import (
    SubscriptionCard,
    SubscriptionState,
    TrialClaimCard,
    TrialOfferCard,
)
from geekvpn.domain.provisioning.errors import FreeTrialAlreadyClaimed
from geekvpn.presentation.bot.handlers import trial as handler
from geekvpn.presentation.bot.handlers.menu import home_keyboard, render_home
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import SubCB, TrialCB

pytestmark = pytest.mark.unit


class Trial:
    def __init__(self, *, available: bool = True, claimed: bool = False) -> None:
        self.available = available
        self.claimed = claimed
        self.claims = 0
        self.after = ""

    async def offer(self, user_id: uuid.UUID) -> TrialOfferCard:
        return TrialOfferCard(available=self.available, traffic_mib=500, duration_days=1)

    async def claim(self, user_id: uuid.UUID) -> TrialClaimCard:
        if self.claimed:
            raise FreeTrialAlreadyClaimed("had it", user_id=1)
        self.claims += 1
        card = SubscriptionCard(
            subscription_id=uuid.uuid4(),
            plan_id=uuid.uuid4(),
            product_name_fa="تست",
            plan_name_fa="تست رایگان",
            state=SubscriptionState.ACTIVE,
        )
        return TrialClaimCard(cards=(card,), pending=0, after_message_fa=self.after)


class Chat:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def answer(self, text: str, **_: Any) -> None:
        self.sent.append(text)


class Query:
    def __init__(self) -> None:
        self.message = Chat()

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        return None


@pytest.fixture
def screens(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    shown: list[tuple[str, Any]] = []

    async def record(query: Any, body: str, *, markup: Any = None) -> None:
        shown.append((body, markup))

    monkeypatch.setattr(handler, "safe_edit", record)
    return shown


def _callbacks(markup: Any) -> list[str]:
    return [button.callback_data for row in markup.inline_keyboard for button in row]


USER = SimpleNamespace(id=uuid.uuid4(), telegram_id=42, first_name="Ali")


def services(trial: Trial) -> Any:
    return SimpleNamespace(trial=trial)


async def test_the_screen_explains_the_trial_before_spending_it(screens: list[Any]) -> None:
    trial = Trial()

    await handler.on_view(Query(), services(trial), user=USER)  # type: ignore[arg-type]

    [(body, markup)] = screens
    assert "۵۰۰" in body
    assert TrialCB(action="claim").pack() in _callbacks(markup)
    assert trial.claims == 0


async def test_claiming_hands_over_a_button_to_the_new_service(screens: list[Any]) -> None:
    trial = Trial()

    await handler.on_claim(Query(), services(trial), user=USER)  # type: ignore[arg-type]

    body, markup = screens[-1]
    assert body.startswith(T.TRIAL_DELIVERED[:10])
    assert any(data.startswith(SubCB.__prefix__) for data in _callbacks(markup))


async def test_a_second_claim_is_told_to_buy_instead(screens: list[Any]) -> None:
    await handler.on_claim(Query(), services(Trial(claimed=True)), user=USER)  # type: ignore[arg-type]

    assert screens[-1][0] == T.TRIAL_ALREADY_CLAIMED


async def test_the_operators_message_follows_the_delivery(screens: list[Any]) -> None:
    trial = Trial()
    trial.after = "آموزش اتصال: t.me/geek/12"
    query = Query()

    await handler.on_claim(query, services(trial), user=USER)  # type: ignore[arg-type]

    assert query.message.sent == ["آموزش اتصال: t.me/geek/12"]


async def test_the_home_screen_offers_the_trial_only_while_it_can_be_had() -> None:
    def labels(markup: Any) -> list[str]:
        return [button.text for row in markup.inline_keyboard for button in row]

    assert not any(T.MENU_TRIAL in label for label in labels(home_keyboard()))
    assert any(T.MENU_TRIAL in label for label in labels(home_keyboard(offer_trial=True)))


async def test_the_home_screen_asks_whether_the_trial_is_still_available() -> None:
    class Wallet:
        async def snapshot(self, user_id: uuid.UUID) -> Any:
            from geekvpn.application.bot.read_models import WalletSnapshot

            return WalletSnapshot()

    class Subs:
        async def list_for_user(self, user_id: uuid.UUID) -> list[Any]:
            return []

    bundle = SimpleNamespace(trial=Trial(available=False), wallet=Wallet(), subscriptions=Subs())
    _, markup = await render_home(user=USER, services=bundle)  # type: ignore[arg-type]
    assert TrialCB(action="view").pack() not in _callbacks(markup)

    bundle.trial = Trial(available=True)
    _, markup = await render_home(user=USER, services=bundle)  # type: ignore[arg-type]
    assert TrialCB(action="view").pack() in _callbacks(markup)
