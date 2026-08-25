"""The admin client must send the fields its endpoints declare.

`test_admin_api_contract.py` compares paths and verbs. It cannot see inside the
body, and that is where the drift was: the ticket reply sent `{ message }` to
an endpoint declaring `bodyFa` and forbidding extras, so the request failed
twice over - the field it wanted missing, the field it got not allowed. The
operator saw "(bodyFa، message)" and no reply was ever posted from the panel.

Read from the OpenAPI schema rather than from the models, because the schema is
what the request is actually validated against - aliases, camel-casing and all.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from geekvpn.presentation.api.app import API_V1_PREFIX, create_app

pytestmark = pytest.mark.integration

ADMIN_API = Path(__file__).resolve().parents[2] / "admin" / "src" / "lib" / "api.ts"

_TEMPLATE = re.compile(r"\$\{[^}]*\}")

#: `mutate<T>('POST', `path`, { a, b })` - the object literal is optional, and
#: only simple `{ key, key: value }` shapes are read. Anything else is skipped
#: rather than guessed at.
_CALL = re.compile(
    r"mutate<[^>]*>\(\s*'(POST|PUT|PATCH|DELETE)',\s*`([^`]+)`\s*,\s*\{([^{}]*)\}",
    re.DOTALL,
)


def _sent() -> list[tuple[str, str, set[str]]]:
    source = ADMIN_API.read_text(encoding="utf-8")
    calls: list[tuple[str, str, set[str]]] = []
    for method, raw, literal in _CALL.findall(source):
        path = raw.split("${qs")[0].replace("${ROOT}", f"{API_V1_PREFIX}/admin")
        path = _TEMPLATE.sub("{id}", path).rstrip("/")
        keys = {
            part.split(":")[0].strip()
            for part in literal.split(",")
            if part.strip() and not part.strip().startswith("...")
        }
        if keys:
            calls.append((method.lower(), path, keys))
    return calls


def _schema() -> dict[str, Any]:
    return create_app().openapi()


def _accepted(schema: dict[str, Any], method: str, path: str) -> set[str] | None:
    """Property names the endpoint's request body allows, or None if it has none."""
    for candidate, operations in schema["paths"].items():
        if _TEMPLATE.sub("{id}", re.sub(r"\{[^}]*\}", "{id}", candidate)) != path:
            continue
        operation = operations.get(method)
        if operation is None:
            continue
        body = operation.get("requestBody")
        if body is None:
            return None
        content = body["content"]["application/json"]["schema"]
        ref = content.get("$ref") or content.get("allOf", [{}])[0].get("$ref")
        if ref is None:
            return None
        model = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]
        return set(model.get("properties", {}))
    return None


def test_the_client_makes_calls_with_bodies() -> None:
    assert len(_sent()) >= 10


def test_every_field_sent_is_a_field_the_endpoint_declares() -> None:
    wrong: list[str] = []
    for method, path, keys in _sent():
        accepted = _accepted(_schema(), method, path)
        if accepted is None:
            continue
        unknown = keys - accepted
        if unknown:
            wrong.append(f"{method.upper()} {path} sends {sorted(unknown)}, accepts {sorted(accepted)}")

    assert not wrong, "the admin client sends fields its endpoints reject:\n  " + "\n  ".join(wrong)


def test_every_required_field_is_sent() -> None:
    """The other half: a missing required field is the same 422."""
    schema = _schema()
    missing: list[str] = []
    for method, path, keys in _sent():
        for candidate, operations in schema["paths"].items():
            if _TEMPLATE.sub("{id}", re.sub(r"\{[^}]*\}", "{id}", candidate)) != path:
                continue
            operation = operations.get(method)
            if operation is None or "requestBody" not in operation:
                continue
            content = operation["requestBody"]["content"]["application/json"]["schema"]
            ref = content.get("$ref") or content.get("allOf", [{}])[0].get("$ref")
            if ref is None:
                continue
            model = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]
            absent = set(model.get("required", [])) - keys
            if absent:
                missing.append(f"{method.upper()} {path} omits required {sorted(absent)}")

    assert not missing, "\n  ".join(missing)
