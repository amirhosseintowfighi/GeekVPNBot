"""One 401 with six different causes, and the log has to say which.

No header, wrong scheme, empty initData, a hash that does not match, data older
than the freshness window, no user object - all answer the same way on purpose,
because telling a caller which half of their header was wrong is free
information for whoever is probing.

That is right for the response and useless for the operator, who then cannot
tell "opened outside Telegram" from "the bot token does not match the one that
served the Mini App" from "this session has been open for twenty minutes".
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_a_rejected_mini_app_call_records_the_reason(client, caplog) -> None:
    with caplog.at_level("INFO"):
        response = client.get(
            "/api/miniapp/storefront", headers={"Authorization": "tma not-real-init-data"}
        )

    assert response.status_code == 401
    assert "miniapp.auth_rejected" in caplog.text


def test_the_credential_itself_is_never_written_to_the_log(client, caplog) -> None:
    """initData is a valid credential until it expires."""
    secret = "user=%7B%22id%22%3A1%7D&hash=deadbeef&auth_date=1"

    with caplog.at_level("INFO"):
        client.get("/api/miniapp/storefront", headers={"Authorization": f"tma {secret}"})

    assert "deadbeef" not in caplog.text
    assert secret not in caplog.text


def test_the_response_still_says_nothing_useful_to_a_prober(client) -> None:
    missing = client.get("/api/miniapp/storefront")
    malformed = client.get("/api/miniapp/storefront", headers={"Authorization": "tma nonsense"})

    assert missing.status_code == malformed.status_code == 401
