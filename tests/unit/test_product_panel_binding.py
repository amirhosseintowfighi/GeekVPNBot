"""A product is bound to a node by the id an operator can actually see.

`ProductPanelBindRequest` took a UUID. Node ids in this schema are opaque
strings - "de-frankfurt-1" - so there was no value the admin panel could send
that would validate, and binding a product was impossible from the only screen
that offers it. Which mattered more than it sounds: an unbound product cannot
be published, and a package under an unpublished product cannot be published
either, so the whole catalogue was stuck.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from geekvpn.application.provisioning import panel_id_for
from geekvpn.presentation.api.schemas_catalog import ProductPanelBindRequest

pytestmark = pytest.mark.unit


def test_a_node_id_is_accepted() -> None:
    body = ProductPanelBindRequest.model_validate({"nodeId": "de-frankfurt-1", "nodeTags": []})

    assert body.node_id == "de-frankfurt-1"


def test_an_empty_node_id_is_refused() -> None:
    with pytest.raises(ValidationError):
        ProductPanelBindRequest.model_validate({"nodeId": "", "nodeTags": []})


def test_the_derived_panel_id_is_stable() -> None:
    """A create and a later renew must derive the same id, or the renew
    addresses an account that does not exist."""
    first = panel_id_for("de-frankfurt-1")
    second = panel_id_for("de-frankfurt-1")

    assert first == second
    assert isinstance(first, uuid.UUID)


def test_two_nodes_never_share_a_panel_id() -> None:
    assert panel_id_for("de-frankfurt-1") != panel_id_for("de-frankfurt-2")


def test_a_node_whose_id_is_already_a_uuid_keeps_it() -> None:
    """The conversion must not fold an id that needs no folding."""
    real = uuid.uuid4()

    assert panel_id_for(str(real)) == real
