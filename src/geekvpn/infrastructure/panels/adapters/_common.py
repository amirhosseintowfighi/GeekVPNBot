"""Conversions shared by adapters, kept out of the domain.

These exist because panels are casual about units and time in ways the domain
refuses to be. Centralising the coercion means one well-tested implementation
instead of five subtly different ones.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from geekvpn.domain.panels.errors import PanelContractViolation


def to_utc(value: Any, *, panel: str, field: str) -> datetime | None:
    """Coerce a panel timestamp into an aware UTC datetime.

    Handles the three encodings these panels actually use: epoch seconds,
    epoch milliseconds, and ISO-8601 strings that are frequently naive.
    A naive string is assumed UTC - every one of these panels stores UTC
    internally even when it renders local time in its own UI.
    """
    if value is None or value == 0 or value == "":
        return None
    if isinstance(value, bool):
        raise PanelContractViolation(f"{field} was a boolean.", panel=panel, field=field)
    if isinstance(value, (int, float)):
        seconds = float(value)
        # Anything past ~2286 in seconds is really milliseconds. 3x-ui uses ms.
        if seconds > 1e11:
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise PanelContractViolation(
                f"{field} was not a usable timestamp.", panel=panel, field=field
            ) from exc
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise PanelContractViolation(
                f"{field} was not ISO-8601.", panel=panel, field=field
            ) from exc
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise PanelContractViolation(
        f"{field} had unexpected type {type(value).__name__}.", panel=panel, field=field
    )


def to_int(value: Any, *, panel: str, field: str, default: int = 0) -> int:
    """Coerce a traffic counter to int.

    Panels return these as int, float, or a numeric string depending on version
    and endpoint, and a `TypeError` deep in a billing calculation is a much
    worse outcome than an explicit contract violation here.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        raise PanelContractViolation(f"{field} was a boolean.", panel=panel, field=field)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip() or default))
        except ValueError as exc:
            raise PanelContractViolation(
                f"{field} was not numeric.", panel=panel, field=field
            ) from exc
    raise PanelContractViolation(
        f"{field} had unexpected type {type(value).__name__}.", panel=panel, field=field
    )


def required_int(item: Mapping[str, Any], key: str, *, panel: str) -> int:
    """A counter the panel must have sent, coerced.

    `to_int(item.get(key), ...)` defaults a missing key to zero, which makes
    "this panel does not report usage under that name" indistinguishable from
    "this customer has used nothing". Traffic sat at zero for days looking
    exactly like an idle account, and there was nothing in any log to say
    otherwise.

    Present-and-null is still zero: panels do send an explicit null for an
    account that has never connected. It is the *absence* of the key that means
    we are reading the wrong field.
    """
    if key not in item:
        raise PanelContractViolation(
            f"{key} was missing from the account payload.", panel=panel, field=key
        )
    return to_int(item[key], panel=panel, field=key)


def require_mapping(value: Any, *, panel: str, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PanelContractViolation(f"Expected a JSON object for {what}.", panel=panel, what=what)
    return value


def now_utc() -> datetime:
    return datetime.now(UTC)


#: How many accounts one subscription-link lookup asks for. A panel holding
#: more customers than this needs paging here; until then a second round trip
#: on every claim would be work nobody is waiting for.
LOOKUP_PAGE = 1000


#: How many accounts one bulk read asks for.
#:
#: This was `max(len(wanted), 100)`, which asks for a hundred rows however many
#: accounts we are actually looking for - so on a panel with more than a
#: hundred users the ones past the first page were never read, and their usage
#: simply stopped moving. Nothing failed; the reading was just absent, which
#: reads as an idle customer.
#:
#: Still a ceiling rather than paging: one request is worth keeping while a
#: shop fits inside it, and `LOOKUP_PAGE` is far past where these panels are
#: comfortable anyway.
BULK_PAGE = 1000

def sub_token(url: str) -> str:
    """The identifying tail of a subscription link.

    Everything after the last slash, minus any query string. The hostname is
    deliberately not compared: the panel reports whatever it was configured
    with, the customer holds whatever they were sent, and those differ behind a
    reverse proxy or a second domain. The token is what names the account, and
    it is long enough that matching on it alone is not a collision risk.
    """
    if not url:
        return ""
    return url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1].strip()
