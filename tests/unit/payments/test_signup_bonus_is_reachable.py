"""The welcome credit is wired to something that actually runs.

`credit_reward` sat in `WalletService` with no caller at all - correct code,
tested, and reachable from nothing. This is the rule this project keeps
relearning, so the wiring gets its own test rather than being assumed.

Structural, because that is the failure: a service registered nowhere and a
setting nobody reads both look exactly like working code from inside a unit
test that constructs them by hand.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from geekvpn.application.platform.settings_service import (
    SETTING_REGISTRY,
    SIGNUP_BONUS_NOTE_FA,
    SIGNUP_BONUS_TOMAN,
)
from geekvpn.domain.base.errors import ValidationError

pytestmark = pytest.mark.unit

SYNC_SCOPE = pathlib.Path("src/geekvpn/infrastructure/di/sync_scope.py")
SCOPE = pathlib.Path("src/geekvpn/infrastructure/di/scope.py")
START = pathlib.Path("src/geekvpn/presentation/bot/handlers/start.py")


def _function(path: pathlib.Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone from {path}")


def test_both_settings_are_in_the_registry():
    """The admin settings screen renders whatever the registry holds, so this
    is also what puts them on the screen."""
    assert SIGNUP_BONUS_TOMAN.key in SETTING_REGISTRY
    assert SIGNUP_BONUS_NOTE_FA.key in SETTING_REGISTRY


def test_it_is_off_until_the_operator_turns_it_on():
    """A default that gave money away on upgrade would be a surprise nobody
    asked for, paid out of the operator's pocket."""
    assert SIGNUP_BONUS_TOMAN.default == 0


def test_the_amount_must_be_a_number():
    """Settings coerce on write, so a typo fails when it is typed rather than
    at 3am when somebody finally starts the bot."""
    with pytest.raises(ValidationError):
        SIGNUP_BONUS_TOMAN.coerce("۵۰۰۰۰")


def test_the_service_is_built_by_the_sync_scope():
    source = SYNC_SCOPE.read_text(encoding="utf-8")

    assert "def signup_bonus(self) -> SignupBonusService:" in source


def test_the_shop_is_passed_to_it():
    """The rule that keeps our promotion out of a reseller's wallet is only as
    good as the shop it is given."""
    source = ast.unparse(_function(SYNC_SCOPE, "signup_bonus"))

    assert "reseller_id=self.reseller_id" in source


def test_the_request_scope_reads_the_settings_and_crosses_over():
    source = ast.unparse(_function(SCOPE, "grant_signup_bonus"))

    assert "SIGNUP_BONUS_TOMAN" in source
    assert "in_shop" in source


def test_start_is_what_calls_it():
    """The one moment a customer is new."""
    source = ast.unparse(_function(START, "on_start"))

    assert "_welcome_credit" in source


def test_a_failure_to_credit_does_not_break_registration():
    """They can be paid by hand. A /start that dies leaves somebody with no
    account at all, which is not a trade worth making for a gift."""
    source = ast.unparse(_function(START, "_welcome_credit"))

    assert "except Exception" in source


def test_nothing_is_announced_when_nothing_was_given():
    """A greeting that announces a gift of nothing is worse than a greeting."""
    source = ast.unparse(_function(START, "_welcome_credit"))

    assert "amount > 0" in source
