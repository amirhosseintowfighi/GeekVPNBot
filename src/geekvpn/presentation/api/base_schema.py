"""The one base class every API model inherits.

The API spoke two dialects. Endpoints backed by a Pydantic response model
serialised their fields as written - ``display_name``, ``telegram_id``,
``max_per_user`` - while the analytics and support endpoints hand-build their
payloads through ``as_dict()`` and have always emitted camelCase: ``labelFa``,
``changePercent``, ``revenueSeries``. Same API, same version, two conventions,
split by an implementation detail no caller can see.

Both front-ends were written against camelCase throughout, which is the larger
half of why the admin panel had 192 type errors and had never compiled.

So camelCase wins, for every model, and the divide disappears. ``by_alias`` is
FastAPI's default when serialising a ``response_model``, so responses change
shape the moment a model inherits this. ``populate_by_name`` keeps *input*
accepting either spelling, so a request body written in snake_case - including
every existing test - still validates.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """Serialises camelCase, accepts either.

    Subclasses may set their own ``model_config``; Pydantic merges it with this
    one rather than replacing it, so ``extra="forbid"`` on a request model
    keeps working alongside the alias generator.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


__all__ = ["ApiModel"]
