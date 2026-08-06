"""Logging must never leak a secret and must always carry a correlation id."""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.logging.context import (
    bind_correlation_id,
    get_correlation_id,
    new_correlation_id,
    reset_correlation_id,
)
from geekvpn.infrastructure.logging.setup import make_redactor

pytestmark = pytest.mark.unit


def test_correlation_id_binds_and_resets() -> None:
    assert get_correlation_id() is None
    token = bind_correlation_id("abc123")
    assert get_correlation_id() == "abc123"
    reset_correlation_id(token)
    assert get_correlation_id() is None


def test_generated_correlation_ids_are_unique() -> None:
    assert new_correlation_id() != new_correlation_id()


def test_redactor_masks_top_level_keys() -> None:
    redact = make_redactor(["password", "token"])
    result = redact(None, "info", {"event": "login", "password": "hunter2"})
    assert result["password"] == "***"
    assert result["event"] == "login"


def test_redactor_masks_nested_and_partial_key_matches() -> None:
    redact = make_redactor(["secret"])
    result = redact(
        None,
        "info",
        {"panel": {"url": "https://p", "api_secret": "x", "nodes": [{"secret_key": "y"}]}},
    )
    panel = result["panel"]
    assert panel["api_secret"] == "***"
    assert panel["nodes"][0]["secret_key"] == "***"
    assert panel["url"] == "https://p"
