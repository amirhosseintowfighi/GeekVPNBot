"""A deploy must actually put the bot on the image it just built.

`docker compose up -d` compares image ids and does nothing when they match, so
the step logged as "restarting the bot onto the new image" could leave the old
container running. The API colours are recreated by name either way and the
front-ends are rebuilt explicitly, so everything else picked up the new code
while the bot kept serving the previous one - with nothing in the deploy output
to say so.

That is how a handler could be written, tested, merged and deployed, and still
answer "I did not understand that".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

DEPLOY = Path(__file__).resolve().parents[2] / "scripts" / "deploy.sh"

#: Services that run the backend image and are started by name rather than
#: replaced as part of the blue/green flip.
LONG_LIVED = ("bot", "worker")


@pytest.mark.parametrize("service", LONG_LIVED)
def test_the_deploy_recreates_it_rather_than_leaving_it_running(service: str) -> None:
    source = DEPLOY.read_text(encoding="utf-8")

    match = re.search(rf"^\$COMPOSE up -d[^\n]*\b{service}\b", source, re.MULTILINE)
    assert match, f"the deploy no longer starts {service}"

    assert "--force-recreate" in match.group(0), (
        f"{service} is started with plain `up -d`, which is a no-op when the "
        "image id has not changed - and a silent one"
    )
