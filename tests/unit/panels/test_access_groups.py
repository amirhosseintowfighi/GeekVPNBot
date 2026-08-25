"""Groups are a selling decision, not a connection detail.

PasarGuard grants access through groups, and which group an account joins
decides which configs it receives - so two customers on the same node can hold
entirely different inbounds. Choosing the wrong one produces an account that
authenticates, appears healthy, and carries nothing the customer can use.

That is why the id goes to the panel and the name goes on the screen, and why
a panel that cannot list them refuses rather than answering with an empty list.
"""

from __future__ import annotations

import pytest

from geekvpn.domain.panels.enums import Capability, PanelKind
from geekvpn.domain.panels.errors import CapabilityNotSupported
from geekvpn.domain.panels.values import PanelGroup
from geekvpn.infrastructure.panels.adapters.marzban import MarzbanAdapter
from geekvpn.infrastructure.panels.adapters.pasarguard import PasarGuardAdapter

pytestmark = pytest.mark.unit


def test_pasarguard_declares_the_capability() -> None:
    assert Capability.ACCESS_GROUPS in PasarGuardAdapter.capabilities


def test_a_panel_without_the_concept_does_not() -> None:
    """Marzban calls the idea inbounds and cannot list them."""
    assert Capability.ACCESS_GROUPS not in MarzbanAdapter.capabilities


async def test_asking_a_panel_that_cannot_answer_is_refused_not_empty() -> None:
    """An empty list reads on screen as "this panel has none configured",
    which is a different thing an operator would act on differently."""

    class Nothing(MarzbanAdapter):
        kind = PanelKind.MARZBAN

    adapter = object.__new__(Nothing)

    with pytest.raises(CapabilityNotSupported):
        await adapter.groups()


def test_a_group_keeps_both_its_id_and_its_name() -> None:
    """The id is what the panel wants back; the name is what an operator
    recognises. Sending the name would work on a panel that accepts either and
    silently grant nothing on one that does not."""
    group = PanelGroup(id="7", name="آلمان پرسرعت")

    assert group.id == "7"
    assert group.name == "آلمان پرسرعت"
    assert group.is_default is False
