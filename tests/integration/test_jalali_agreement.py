"""The bot, the admin panel and the Mini App must show the same date.

Three implementations of the same calendar, in two languages. The admin panel's
copy drifted - it returned month 18 for late August, which the panel rendered
as "۶ undefined ۱۴۰۵" - while the Mini App's had already been corrected and the
bot's was right all along. Each file's comment claimed to be a port of the bot.

A customer reading one expiry date in the bot and a different one in the Mini
App has no way to know which to believe, so the two ports are pinned to the
Python original here, where all three are in scope.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from geekvpn.presentation.bot.ui.fa import to_jalali

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
PORTS = (ROOT / "admin" / "src" / "lib" / "jalali.ts", ROOT / "miniapp" / "src" / "lib" / "jalali.ts")


def test_both_frontends_carry_the_same_port() -> None:
    """Two copies that disagree is how one of them stayed broken."""
    sources = [path.read_text(encoding="utf-8") for path in PORTS]

    assert sources[0] == sources[1], (
        "admin/src/lib/jalali.ts and miniapp/src/lib/jalali.ts have diverged; "
        "one of them is now wrong and nothing else will tell you which"
    )


@pytest.mark.parametrize(
    ("gregorian", "expected"),
    [
        ("2026-03-21", (1405, 1, 1)),
        ("2026-03-20", (1404, 12, 29)),
        ("2026-08-24", (1405, 6, 2)),
        ("2026-07-23", (1405, 5, 1)),
    ],
)
def test_the_python_original_is_what_the_ports_claim_to_match(
    gregorian: str, expected: tuple[int, int, int]
) -> None:
    """The anchors the TypeScript suites assert, checked against the source."""
    moment = datetime.fromisoformat(gregorian).replace(tzinfo=UTC)

    assert to_jalali(moment) == expected


def test_the_port_asserts_those_same_anchors() -> None:
    """A port with no anchor in common with its original is not pinned to it."""
    suite = (ROOT / "admin" / "tests" / "jalali.test.ts").read_text(encoding="utf-8")

    assert re.search(r"1405,\s*1,\s*1", suite), "Nowruz is not pinned in the admin suite"
    assert re.search(r"1405,\s*6,\s*2", suite), "the date that broke is not pinned"
