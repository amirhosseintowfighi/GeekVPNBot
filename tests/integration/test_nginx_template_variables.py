"""Every ${VAR} in the nginx template must be in the envsubst allowlist.

`envsubst` is called with an explicit variable list on purpose: without one it
would also replace nginx's own variables - `$host`, `$request_uri`,
`$active_api` - with empty strings, producing a config that is syntactically
valid and completely wrong.

The cost of that allowlist is that adding a `${VAR}` to the template and
forgetting to list it produces the same silent blanking for that one variable.
`set $miniapp_upstream ;` is a config error nginx would catch, but
`server_name ;` is not, and neither is an empty allowlist entry - so this
checks the two lists against each other instead of trusting them to be kept in
step by hand.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

NGINX = Path(__file__).resolve().parents[2] / "docker" / "nginx"
TEMPLATE = NGINX / "templates" / "geekvpn.conf"
ENTRYPOINT = NGINX / "entrypoint.sh"


def _allowlist() -> set[str]:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    match = re.search(r"envsubst\s+'([^']*)'", source)
    assert match, "the entrypoint no longer calls envsubst with a variable list"
    return set(re.findall(r"\$\{(\w+)\}", match.group(1)))


def _used_in_template() -> set[str]:
    return set(re.findall(r"\$\{(\w+)\}", TEMPLATE.read_text(encoding="utf-8")))


def test_every_template_variable_is_substituted() -> None:
    missing = _used_in_template() - _allowlist()

    assert not missing, (
        f"the template uses {sorted(missing)}, which envsubst will replace with "
        "nothing because they are not in its allowlist"
    )


def test_every_substituted_variable_is_set_before_use() -> None:
    """A listed name that nothing exports blanks just as silently."""
    source = ENTRYPOINT.read_text(encoding="utf-8")
    unset = [
        name
        for name in _allowlist()
        if not re.search(rf"^\s*(export\s+)?{name}=", source, re.MULTILINE)
        and not re.search(rf"^export .*\b{name}\b", source, re.MULTILINE)
    ]

    assert not unset, f"listed for substitution but never assigned: {sorted(unset)}"
