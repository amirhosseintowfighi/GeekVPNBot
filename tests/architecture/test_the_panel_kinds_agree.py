"""The admin panel knows the same panel kinds the backend does.

`admin/src/lib/types.ts` declared `'xui' | 'marzban' | 'marzneshin' |
'hiddify'`: two kinds that do not exist and three missing, including
`pasarguard` - the panel every node in production runs on. It went unnoticed
because nothing compared against the type; the dropdown that actually creates
nodes has its own list, and that one was right.

A drift nobody notices is one that shows up as a blank cell on an operator's
screen, or as a kind they cannot select. Both lists are read from source here
rather than trusted.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from geekvpn.domain.panels.enums import PanelKind

pytestmark = pytest.mark.architecture

ROOT = pathlib.Path(__file__).resolve().parents[2]
TYPES = ROOT / "admin" / "src" / "lib" / "types.ts"
DIALOG = ROOT / "admin" / "src" / "components" / "feature" / "node-dialog.tsx"
LABELS = ROOT / "admin" / "src" / "app" / "panels" / "page.tsx"


def _union() -> set[str]:
    source = TYPES.read_text(encoding="utf-8")
    # Up to the next declaration: the file puts no blank line between type
    # aliases, so splitting on one swallows the rest of the file.
    tail = source[source.index("export type PanelKind") + 1 :]
    body = tail.split("export type", 1)[0]
    return set(re.findall(r"'([a-z0-9_]+)'", body))


def _dropdown() -> set[str]:
    source = DIALOG.read_text(encoding="utf-8")
    body = source[source.index("const PANEL_KINDS") :].split("] as const", 1)[0]
    return set(re.findall(r"value: '([a-z0-9_]+)'", body))


def _labels() -> set[str]:
    source = LABELS.read_text(encoding="utf-8")
    body = source[source.index("const PANEL_KIND_LABEL") :].split("}", 1)[0]
    return set(re.findall(r"^\s{2}([a-z0-9_]+):", body, re.MULTILINE))


def _backend() -> set[str]:
    return {kind.value for kind in PanelKind}


def test_the_type_lists_every_kind_the_backend_has():
    assert _union() == _backend()


def test_the_dropdown_offers_every_kind():
    """A kind missing here cannot be chosen, so a panel the platform supports
    is unreachable from the only screen that creates nodes."""
    assert _dropdown() == _backend()


def test_every_kind_has_a_label():
    """Without one the panels screen renders an empty cell where the operator
    expects to read which software a node runs."""
    assert _labels() == _backend()
