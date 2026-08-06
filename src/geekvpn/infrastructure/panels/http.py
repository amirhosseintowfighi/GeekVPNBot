"""Shared HTTP transport for panel adapters.

Every adapter gets the same operational behaviour for free, which is the point:
retry policy, timeout handling, error translation and credential redaction are
things you must not re-implement (and re-get-wrong) five times.

Design notes:

- **Retries only on retryable failures.** A 401 is never retried; hammering a
  panel with bad credentials is how you get the platform IP-banned.
- **Exponential backoff with full jitter.** Ten panels all retrying on a fixed
  1s schedule after a blip produces a thundering herd that keeps the panel down.
- **`Retry-After` is honoured** when the panel sends it.
- **Everything is translated.** No `httpx` exception may escape; the domain
  error taxonomy is the only thing callers see.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Mapping
from typing import Any

import httpx

from geekvpn.domain.panels.errors import (
    PanelAuthFailed,
    PanelContractViolation,
    PanelRateLimited,
    PanelUnreachable,
)

#: Backoff base; attempt N waits a random value in [0, BASE * 2**N).
BACKOFF_BASE_SECONDS = 0.25
BACKOFF_CAP_SECONDS = 8.0


class PanelHttpClient:
    """A thin, panel-agnostic wrapper over `httpx.AsyncClient`."""

    def __init__(
        self,
        *,
        base_url: str,
        panel_name: str,
        timeout_seconds: float = 15.0,
        max_attempts: int = 3,
        verify_tls: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._panel_name = panel_name
        self._max_attempts = max_attempts
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
            verify=verify_tls,
            transport=transport,
            follow_redirects=True,
            headers={"Accept": "application/json", "User-Agent": "GeekVPN/0.3"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def cookies(self) -> httpx.Cookies:
        """Exposed for the x-ui family, which authenticates with a session cookie."""
        return self._client.cookies

    async def request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        data: Any = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        expected: tuple[int, ...] = (200, 201, 204),
        allow_status: tuple[int, ...] = (),
    ) -> httpx.Response:
        """Perform a request with retry and error translation.

        `allow_status` lets a caller handle a status itself - typically 404,
        which several adapters treat as "absent", not "failed".
        """
        last_error: Exception | None = None

        for attempt in range(self._max_attempts):
            try:
                response = await self._client.request(
                    method, url, json=json, data=data, params=params, headers=headers
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt + 1 < self._max_attempts:
                    await self._sleep_backoff(attempt)
                    continue
                raise PanelUnreachable(
                    f"{type(exc).__name__} contacting the panel.",
                    panel=self._panel_name,
                    url=url,
                ) from exc

            if response.status_code in expected or response.status_code in allow_status:
                return response

            if response.status_code in (401, 403):
                # Terminal by design. See module docstring.
                raise PanelAuthFailed(panel=self._panel_name, status=response.status_code)

            if response.status_code == 429:
                retry_after = _retry_after(response)
                if attempt + 1 < self._max_attempts:
                    await asyncio.sleep(
                        retry_after if retry_after is not None else _backoff_delay(attempt)
                    )
                    continue
                raise PanelRateLimited(panel=self._panel_name, retry_after_seconds=retry_after)

            if response.status_code >= 500:
                if attempt + 1 < self._max_attempts:
                    await self._sleep_backoff(attempt)
                    continue
                raise PanelUnreachable(
                    f"Panel returned HTTP {response.status_code}.",
                    panel=self._panel_name,
                    status=response.status_code,
                )

            # 4xx that is not auth or rate limiting: our request was wrong.
            raise PanelContractViolation(
                f"Panel returned unexpected HTTP {response.status_code}.",
                panel=self._panel_name,
                status=response.status_code,
                body=_safe_body(response),
            )

        raise PanelUnreachable(  # pragma: no cover - loop always returns or raises
            "Exhausted retries.", panel=self._panel_name
        ) from last_error

    async def _sleep_backoff(self, attempt: int) -> None:
        await asyncio.sleep(_backoff_delay(attempt))

    def json(self, response: httpx.Response) -> Any:
        """Parse JSON, translating a malformed body into a contract violation."""
        try:
            return response.json()
        except ValueError as exc:
            raise PanelContractViolation(
                "Panel response was not valid JSON.",
                panel=self._panel_name,
                body=_safe_body(response),
            ) from exc


def _backoff_delay(attempt: int) -> float:
    """Full jitter: uniform in [0, min(cap, base * 2**attempt))."""
    ceiling = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2**attempt))
    return random.uniform(0, ceiling)  # noqa: S311 - jitter, not cryptography


def _retry_after(response: httpx.Response) -> int | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return None


def _safe_body(response: httpx.Response, limit: int = 400) -> str:
    """A truncated body for diagnostics.

    Truncated because panel error pages can be entire HTML documents, and we do
    not want one bad request to write a megabyte into the log pipeline.
    """
    try:
        return response.text[:limit]
    except Exception:  # pragma: no cover - defensive
        return "<unreadable>"
