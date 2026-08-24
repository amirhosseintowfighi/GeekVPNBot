"""A 422 must say which field, in the log as well as the response.

Diagnosing one from `docker logs` used to be impossible: the line named the
path and nothing else, so finding the offending field meant asking whoever hit
it to open devtools - and guessing in the meantime.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_a_rejected_request_logs_the_field_that_was_wrong(client, caplog) -> None:
    with caplog.at_level("INFO"):
        response = client.post("/api/v1/admin/auth/login", json={"username": "amir"})

    assert response.status_code == 422
    assert "password" in caplog.text
    assert "http.validation_failed" in caplog.text


def test_the_rejected_value_itself_is_not_logged(client, caplog) -> None:
    """A rejected login body holds a password."""
    with caplog.at_level("INFO"):
        client.post(
            "/api/v1/admin/auth/login",
            json={"username": "amir", "password": 12345, "totpCode": "hunter2-in-the-wrong-field"},
        )

    assert "hunter2-in-the-wrong-field" not in caplog.text


def test_a_domain_error_keeps_its_own_persian_message(client) -> None:
    """The specific sentence beats the generic one keyed off the code.

    `admin_actor_id` refuses with "برای این اقدام، حساب تلگرام مدیر باید متصل
    باشد" - which names the actual problem. Rendering "اطلاعات واردشده درست
    نیست" instead sent an operator to re-read a form that was never wrong.
    """
    from geekvpn.presentation.api.text_fa import GENERIC, user_message

    specific = "برای این اقدام، حساب تلگرام مدیر باید متصل باشد."

    assert user_message("validation_error", specific) == specific
    assert user_message("validation_error", "Request validation failed.") != specific
    assert user_message("no_such_code", "An internal detail.") == GENERIC
