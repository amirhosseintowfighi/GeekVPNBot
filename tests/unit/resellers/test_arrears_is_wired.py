"""The enforcer has to be constructed, not merely written.

This project's recurring failure is correct code nothing reaches - a
provisioning layer with no caller, a keyring installer nobody installed, a
generated nginx file nobody included. An arrears enforcer that is optional in
the service and absent from the container would be exactly that shape, and the
symptom would be a credit limit that silently does not exist.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

SCOPE = pathlib.Path("src/geekvpn/infrastructure/di/scope.py")


def _tree() -> ast.Module:
    return ast.parse(SCOPE.read_text(encoding="utf-8"))


def test_the_container_builds_an_arrears_enforcer():
    built = {
        node.func.id
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "ArrearsEnforcer" in built


def test_the_reseller_service_is_given_one():
    """Optional in the constructor so the service stays testable without a
    panel behind it. That default must not be what production runs."""
    for node in ast.walk(_tree()):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ResellerService"
        ):
            assert "arrears" in {kw.arg for kw in node.keywords}
            return
    pytest.fail("nothing in the container constructs a ResellerService")
