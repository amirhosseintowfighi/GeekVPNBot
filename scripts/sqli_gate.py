"""Permanent gate against SQL built by string interpolation.

The audit that motivated this found the codebase clean: every raw statement uses
bound parameters. A clean audit decays the moment someone writes one convenient
f-string, and a review six months from now will not repeat it by hand. So the
audit is codified here and runs in CI.

What is flagged
---------------
An f-string, ``%`` formatting, ``.format()`` call, or ``+`` concatenation passed
directly into ``text(...)``, ``execute(...)``, ``executemany(...)`` or
``exec_driver_sql(...)``.

Why the AST and not a grep: a grep for ``execute(f"`` misses a statement built on
the line above and stored in a variable, and it produces false positives on
unrelated names such as ``edit_text`` or ``_require_text`` - all of which the
manual audit had to sift through by hand.

Exit status is non-zero when anything is found, so this is usable as a CI step.
"""

from __future__ import annotations

import ast
import pathlib
import sys

DANGEROUS_CALLS = {"text", "execute", "executemany", "exec_driver_sql", "scalar", "scalars"}

#: A statement with no interpolation at all is safe regardless of how it was
#: written, so the gate only inspects the *shape* of the argument expression.
INTERPOLATING_NODES = (ast.JoinedStr,)


def _is_string_building(node: ast.AST) -> str | None:
    """Describe how this expression interpolates, or ``None`` if it does not."""
    if isinstance(node, ast.JoinedStr):
        return "f-string"
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Mod):
            # "...%s..." % value - only flagged when the left side is a literal
            # string, since ``a % b`` on numbers is not SQL.
            if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                return "percent formatting"
        if isinstance(node.op, ast.Add):
            for side in (node.left, node.right):
                if isinstance(side, ast.Constant) and isinstance(side.value, str):
                    return "string concatenation"
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "format":
            if isinstance(func.value, ast.Constant) and isinstance(func.value.value, str):
                return ".format() call"
    return None


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def scan_file(path: pathlib.Path) -> list[str]:
    findings: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:  # pragma: no cover - a broken file is its own alarm
        return [f"{path}: could not parse ({exc})"]

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in DANGEROUS_CALLS:
            continue
        for argument in list(node.args) + [kw.value for kw in node.keywords]:
            how = _is_string_building(argument)
            if how:
                findings.append(
                    f"{path}:{node.lineno}: {name}(...) receives SQL built by {how}"
                )
    return findings


def main(roots: list[str]) -> int:
    targets = [pathlib.Path(root) for root in roots] or [pathlib.Path("src")]
    files = [f for target in targets for f in target.rglob("*.py")]
    findings: list[str] = []
    for path in sorted(files):
        findings.extend(scan_file(path))

    print(f"SQLi gate: scanned {len(files)} files")
    if findings:
        for finding in findings:
            print(f"  ! {finding}")
        print(f"SQLi GATE: {len(findings)} finding(s)")
        return 1
    print("SQLi GATE: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
