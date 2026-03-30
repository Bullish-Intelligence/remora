from __future__ import annotations

import ast
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "remora"


def test_production_code_uses_explicit_errors_not_assert() -> None:
    violating_files: list[str] = []

    for path in _SRC_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        if any(isinstance(node, ast.Assert) for node in ast.walk(tree)):
            violating_files.append(str(path.relative_to(_SRC_ROOT.parent.parent)))

    assert violating_files == [], (
        "Production code must raise explicit runtime errors instead of using assert: "
        + ", ".join(sorted(violating_files))
    )
