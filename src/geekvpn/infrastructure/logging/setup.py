"""Structured logging.

JSON in every deployed environment, human-readable colours locally.
Stdlib ``logging`` (uvicorn, sqlalchemy, aiogram) is routed through the same
structlog pipeline so there is exactly one log format in the system.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable, MutableMapping
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from geekvpn.infrastructure.logging.context import get_correlation_id

_REDACTED = "***"

#: A Telegram bot token: the bot's numeric id, a colon, then the secret. Bot
#: API URLs carry it in the path (`/bot<id>:<secret>/method`), so any line
#: that quotes a request URL - an HTTP client's request log, an exception
#: message - quotes the token with it.
_BOT_TOKEN = re.compile(r"(?<!\d)(\d{6,12}):[A-Za-z0-9_-]{30,}")


def _mask_tokens(value: Any) -> Any:
    if isinstance(value, str):
        return _BOT_TOKEN.sub(lambda m: f"{m.group(1)}:{_REDACTED}", value)
    if isinstance(value, dict):
        return {k: _mask_tokens(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(_mask_tokens(v) for v in value)
    return value


def mask_bot_tokens(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
    """Keep a bot token out of the output, whatever logged it.

    The id before the colon stays, so a line still says which bot it was
    about - ours or which reseller's - without being able to act as it.
    """
    for key in list(event_dict):
        event_dict[key] = _mask_tokens(event_dict[key])
    return event_dict


def _add_correlation_id(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    correlation_id = get_correlation_id()
    if correlation_id is not None:
        event_dict["correlation_id"] = correlation_id
    return event_dict


def make_redactor(keys: Iterable[str]) -> Processor:
    """Redact sensitive values by key name, at any depth.

    This is a safety net, not a licence to log secrets. Panel credentials,
    tokens and Telegram ``initData`` must never be passed to the logger at all.
    """
    lowered = tuple(k.lower() for k in keys)

    def _redact_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (_REDACTED if any(s in k.lower() for s in lowered) else _redact_value(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [_redact_value(v) for v in value]
        return value

    def processor(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
        for key in list(event_dict):
            if any(s in key.lower() for s in lowered):
                event_dict[key] = _REDACTED
            else:
                event_dict[key] = _redact_value(event_dict[key])
        return event_dict

    return processor


def configure_logging(
    *,
    level: str = "INFO",
    json_output: bool = True,
    redact_keys: Iterable[str] = (),
    service: str = "geekvpn",
) -> None:
    """Idempotent. Safe to call from every entrypoint."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _add_correlation_id,
        structlog.processors.StackInfoRenderer(),
        timestamper,
        make_redactor(redact_keys),
    ]

    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[
            *shared,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            # Last before rendering, so it also sees exception text and the
            # message of a record some library logged.
            mask_bot_tokens,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Uvicorn ships its own handlers; strip them so nothing is logged twice.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "aiogram", "alembic"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    # Their INFO line is the full request URL, and a Bot API URL is the bot's
    # token: every notification wrote ours, and every reseller's, to stdout.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)

    structlog.contextvars.bind_contextvars(service=service)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger
