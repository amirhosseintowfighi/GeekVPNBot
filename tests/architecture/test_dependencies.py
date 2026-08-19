"""Everything ``src`` imports must be installable from the runtime dependencies.

``httpx`` was declared only under the ``dev`` extra while
``infrastructure/panels/http.py`` imported it at module scope, and
``di/scope.py`` imports that module. So the production image - built with
``pip install "."``, no extras - could not construct the container at all: the
API, the bot, the worker and ``create_admin`` each died on
``ModuleNotFoundError`` at import time.

Nothing caught it because every developer machine and every CI job installs
``.[dev]``, where httpx is present. The layering contract in
``test_layering.py`` did not either: it governs which of *our* packages may
import which, and says nothing about whether a third-party import will exist
when the thing actually runs.

This resolves each imported top-level module to the distribution that provides
it and checks that distribution appears in the transitive closure of
``[project].dependencies``, so a dev-only or entirely undeclared import fails
here rather than on a server.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, packages_distributions, requires
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def _canonical(requirement: str) -> str:
    """Distribution name out of a requirement string, PEP 503 normalised."""
    for terminator in "<>=!~;[ (":
        requirement = requirement.split(terminator)[0]
    return requirement.strip().lower().replace("_", "-").replace(".", "-")


def runtime_closure() -> set[str]:
    """Declared runtime dependencies plus everything they pull in.

    Transitive, because a direct import of something a declared dependency
    installs (``anyio`` via ``starlette``, say) is present in the image and
    should not fail this test. Extra-gated requirements are skipped: they are
    exactly what does *not* get installed.
    """
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pending = [_canonical(item) for item in declared["project"]["dependencies"]]
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            dependencies = requires(name) or []
        except PackageNotFoundError:  # pragma: no cover - not installed here
            continue
        pending.extend(_canonical(item) for item in dependencies if "extra ==" not in item)
    return seen


def third_party_imports() -> dict[str, str]:
    """Top-level module names imported anywhere under ``src``, and one file
    that imports each - so a failure names somewhere to look."""
    found: dict[str, str] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                if name in sys.stdlib_module_names or name == "geekvpn":
                    continue
                found.setdefault(name, str(path.relative_to(ROOT)))
    return found


def test_every_third_party_import_is_a_runtime_dependency() -> None:
    installed = runtime_closure()
    providers = packages_distributions()

    missing: list[str] = []
    for module, source in sorted(third_party_imports().items()):
        distributions = {_canonical(name) for name in providers.get(module, [])}
        if not distributions:
            # Not installed in this environment at all, so it cannot be a
            # runtime dependency either.
            missing.append(f"{module} (no installed distribution provides it) - {source}")
        elif not distributions & installed:
            missing.append(f"{module} (from {'/'.join(sorted(distributions))}) - {source}")

    assert not missing, (
        "these are imported by src but are not installed by "
        "`pip install .`, so the production image raises ModuleNotFoundError "
        "on import:\n  " + "\n  ".join(missing)
    )
