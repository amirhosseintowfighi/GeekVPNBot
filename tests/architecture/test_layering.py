"""Architecture is a test, not a document.

If someone imports SQLAlchemy into the domain, this fails in CI on the pull
request - not in a code review six weeks later.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

pytestmark = pytest.mark.architecture

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "geekvpn"

FORBIDDEN_IMPORTS = {
    "domain": (
        "sqlalchemy",
        "fastapi",
        "aiogram",
        "redis",
        "pydantic",
        "structlog",
        "geekvpn.application",
        "geekvpn.infrastructure",
        "geekvpn.presentation",
    ),
    "application": (
        "sqlalchemy",
        "fastapi",
        "aiogram",
        "redis",
        "geekvpn.infrastructure",
        "geekvpn.presentation",
    ),
    "infrastructure": ("geekvpn.presentation",),
}


def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize("layer", sorted(FORBIDDEN_IMPORTS))
def test_layer_does_not_import_forbidden_modules(layer: str) -> None:
    forbidden = FORBIDDEN_IMPORTS[layer]
    violations: list[str] = []

    for path in (SRC / layer).rglob("*.py"):
        for module in _imported_modules(path):
            for banned in forbidden:
                if module == banned or module.startswith(f"{banned}."):
                    violations.append(f"{path.relative_to(SRC)} imports {module}")

    assert not violations, "Clean Architecture violation:\n" + "\n".join(violations)


def test_no_relative_imports_anywhere() -> None:
    """Absolute imports only - relative imports hide layer violations."""
    violations = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.level > 0
    ]
    assert not violations, f"relative imports found in: {violations}"


@pytest.mark.skipif(
    subprocess.run(
        [sys.executable, "-c", "import importlinter"], capture_output=True, check=False
    ).returncode
    != 0,
    reason="import-linter is not installed",
)
def test_import_linter_contracts_pass() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "importlinter.cli", "lint"],
        capture_output=True,
        text=True,
        check=False,
        cwd=SRC.parents[1],
    )
    assert result.returncode == 0, result.stdout + result.stderr
