"""A usage counter the panel did not send is an error, not a zero.

`to_int(item.get("used_traffic"), ...)` defaults a missing key to zero. So
"this panel reports usage under a different name" and "this customer has used
nothing" produced the same row, and the usage figure sat at zero looking
exactly like an idle account - with nothing in any log to say otherwise. Hours
went into telling those two apart by hand.

Present-and-null is still zero. Panels do send an explicit null for an account
that has never connected, and that is a real answer. It is the *absence* of the
key that means we are reading the wrong field.

The sweep catches this per node and records it against that node, so a panel
whose payload we misread is now a named failure in the worker log instead of a
table full of silent zeros.
"""

from __future__ import annotations

import pytest

from geekvpn.domain.panels.errors import PanelContractViolation
from geekvpn.infrastructure.panels.adapters._common import required_int

pytestmark = pytest.mark.unit


def test_a_missing_counter_is_refused():
    """The bug. This used to return 0 and look like a quiet customer."""
    with pytest.raises(PanelContractViolation):
        required_int({"username": "ali"}, "used_traffic", panel="pasarguard")


def test_the_error_names_the_field_it_wanted():
    """A failure that says "something went wrong on pasarguard" sends somebody
    reading panel source for an afternoon."""
    with pytest.raises(PanelContractViolation) as raised:
        required_int({}, "used_traffic", panel="pasarguard")

    assert "used_traffic" in str(raised.value)


def test_an_explicit_null_really_is_zero():
    """An account that has never connected. A real answer, not a gap."""
    assert required_int({"used_traffic": None}, "used_traffic", panel="marzban") == 0


def test_a_real_reading_comes_through():
    assert required_int({"used_traffic": 3_693_671_383}, "used_traffic", panel="marzban") == (
        3_693_671_383
    )


def test_a_counter_sent_as_a_string_is_still_a_counter():
    """Panels do this, and it varies by version and endpoint."""
    assert required_int({"used_traffic": "1024"}, "used_traffic", panel="marzban") == 1024


def test_a_float_is_truncated_rather_than_refused():
    assert required_int({"used_traffic": 2048.9}, "used_traffic", panel="marzban") == 2048


def test_nonsense_is_still_refused():
    with pytest.raises(PanelContractViolation):
        required_int({"used_traffic": "quite a lot"}, "used_traffic", panel="marzban")
