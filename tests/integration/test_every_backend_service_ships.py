"""Every service running the backend code must get the code a deploy builds.

The bot had no `image:` of its own, so Compose named it after the project and
service - `geekvpn-bot:latest`. `scripts/deploy.sh` builds the idle API colour,
nginx and the two front-ends, and nothing has ever built that tag. So every
deploy shipped new code to the API, the worker and both front-ends, and the bot
went on running whatever image existed from the first install.

Nothing said so. The deploy logged "restarting the bot onto the new image" and
printed "Running", because `up -d` compares image ids and they matched: the
image really was unchanged. A handler could be written, tested, merged and
deployed and still never run.

This is the same failure this project keeps producing - correct code nothing
reaches - moved down a layer, from a function nobody calls to an image nobody
builds.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.prod.yml"
DEPLOY = ROOT / "scripts" / "deploy.sh"

#: Services that run the Python backend. Each must resolve to the image the
#: deploy actually builds, not one named after itself.
BACKEND_SERVICES = ("api_blue", "api_green", "bot", "worker")


class _Loader(yaml.SafeLoader):
    """Compose's `!override` and `!reset` tags are not YAML the parser knows."""


def _passthrough(loader, suffix, node):
    """Keep the value, drop the tag. What the tag means to Compose does not
    matter here; only the images do."""
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)


_Loader.add_multi_constructor("!", _passthrough)


def _services() -> dict:
    # `_Loader` subclasses SafeLoader; the only thing added is a passthrough
    # for Compose's own `!override` tag, which constructs no objects of its
    # own. S506 is right to ask, and this is the answer.
    return yaml.load(
        COMPOSE.read_text(encoding="utf-8"), Loader=_Loader  # noqa: S506
    )["services"]


@pytest.mark.parametrize("service", BACKEND_SERVICES)
def test_it_shares_the_backend_image(service: str) -> None:
    services = _services()
    image = services[service].get("image")

    assert image, (
        f"{service} declares no image, so Compose names one after the project "
        "and service - a tag the deploy does not build"
    )
    assert image == services["api_blue"]["image"], (
        f"{service} runs the same codebase as the API on a different tag, which "
        "is two chances to run different halves of it"
    )


def test_the_deploy_builds_that_image() -> None:
    """Named services, so sharing a tag is not the only thing holding it up."""
    build = re.search(r"^\$COMPOSE build[^\n|]*", DEPLOY.read_text(encoding="utf-8"), re.MULTILINE)
    assert build, "the deploy no longer builds anything"

    missing = [name for name in ("bot", "worker") if name not in build.group(0)]
    assert not missing, f"not in the deploy's build list: {missing}"
