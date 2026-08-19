"""One API, one spelling.

Endpoints backed by a Pydantic model serialised their fields as written -
``display_name``, ``telegram_id``, ``max_per_user`` - while every endpoint that
hand-builds its payload through ``as_dict()`` has always emitted camelCase:
``labelFa``, ``changePercent``, ``revenueSeries``. Same API, same version, two
conventions, divided by an implementation detail no caller can see.

Both front-ends were written against camelCase throughout. That mismatch is the
larger half of the 192 type errors that meant the admin panel had never
compiled, and none of it was visible from inside Python: the response models
were correct, the tests read status codes rather than field names, and the
schema the front-end was built against lived in a different language.

So this asserts the convention on the OpenAPI schema itself - the same document
a client generates its types from.
"""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI

pytestmark = pytest.mark.architecture

#: Field names that are not ours to spell. OAuth 2 fixes these on the wire.
STANDARD_FIELDS: frozenset[str] = frozenset(
    {"access_token", "refresh_token", "token_type", "expires_in"}
)

_SNAKE = re.compile(r"^[a-z]+(_[a-z0-9]+)+$")


def test_every_response_field_is_camel_case(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]

    offenders: list[str] = []
    for name, model in sorted(schemas.items()):
        for field in sorted(model.get("properties", {})):
            if field in STANDARD_FIELDS or not _SNAKE.match(field):
                continue
            offenders.append(f"{name}.{field}")

    assert not offenders, (
        "these serialise as snake_case while the rest of the API answers in "
        "camelCase; inherit ApiModel so the alias generator applies:\n  " + "\n  ".join(offenders)
    )
