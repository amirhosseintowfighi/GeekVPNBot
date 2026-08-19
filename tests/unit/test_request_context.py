"""Which address a request is credited with.

`request_context` fed three security decisions at once - the admin IP
allowlist, the admin-login rate-limit key, and the `ip` column of every audit
row - and it read the *leftmost* `X-Forwarded-For` entry. That entry is written
by the caller. Anyone could therefore choose the address that the allowlist
checked, the address that their login attempts were counted against, and the
address the audit log would blame afterwards.
"""

from __future__ import annotations

import dataclasses

import pytest
from starlette.requests import Request

from geekvpn.infrastructure.di.container import Container
from geekvpn.presentation.api.security import request_context

pytestmark = pytest.mark.unit


def _request(headers: dict[str, str], *, client: str = "172.20.0.5") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "path": "/",
            "client": (client, 51234),
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        }
    )


def _behind(container: Container, proxies: int) -> Container:
    security = container.settings.security.model_copy(update={"trusted_proxy_count": proxies})
    settings = container.settings.model_copy(update={"security": security})
    return dataclasses.replace(container, settings=settings)


def test_a_client_supplied_forwarded_entry_cannot_choose_its_own_address(
    container: Container,
) -> None:
    behind_one_proxy = _behind(container, 1)
    # The client sent "203.0.113.9"; our nginx then appended what it actually saw.
    request = _request({"X-Forwarded-For": "203.0.113.9, 198.51.100.7"})

    assert request_context(request, behind_one_proxy).ip == "198.51.100.7"


def test_forwarded_headers_are_ignored_with_no_proxy_in_front(container: Container) -> None:
    """With nothing in front of the app the header is unauthenticated input and
    there is no reason for it to exist, so the socket address wins."""
    request = _request({"X-Forwarded-For": "203.0.113.9"}, client="10.1.2.3")

    assert request_context(request, _behind(container, 0)).ip == "10.1.2.3"


def test_an_unusable_address_is_reported_as_unknown(container: Container) -> None:
    request = _request({"X-Forwarded-For": "not-an-address"}, client="also-not-an-address")

    assert request_context(request, _behind(container, 1)).ip is None
