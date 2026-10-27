"""The bot must run as exactly one process, whatever `.env` says.

uvicorn reads any `UVICORN_*` environment variable as its own option, and the
shared `.env` sets `UVICORN_WORKERS=4` for the API. The bot container loads
the same file, so it silently started four workers. Each one registered every
webhook at start-up - which is what tripped Telegram's flood limit on the Iran
server - and in polling mode each would fetch the same updates and could
answer a customer twice. A `--workers` flag on the command line beats the
environment, so it is pinned there.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


class _Loader(yaml.SafeLoader):
    """Compose's `!override` and `!reset` tags are not YAML the parser knows."""


def _passthrough(loader: _Loader, suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)  # type: ignore[arg-type]


_Loader.add_multi_constructor("!", _passthrough)


def _bot(name: str) -> dict[str, Any]:
    text = (ROOT / name).read_text(encoding="utf-8")
    return yaml.load(text, Loader=_Loader)["services"].get("bot") or {}  # noqa: S506


def _workers(command: list[str]) -> str | None:
    for i, arg in enumerate(command):
        if arg == "--workers" and i + 1 < len(command):
            return command[i + 1]
        if arg.startswith("--workers="):
            return arg.split("=", 1)[1]
    return None


def test_the_production_bot_pins_a_single_worker() -> None:
    # The production overlay inherits the base command unless it sets its own.
    command = (
        _bot("docker-compose.prod.yml").get("command") or _bot("docker-compose.yml")["command"]
    )

    assert "uvicorn" in command[0]
    assert _workers(command) == "1", f"the bot command does not pin --workers 1: {command}"
