"""Verify test fixtures are valid Python."""

import ast
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent


def test_simple_pym_is_valid_python() -> None:
    """simple.pym should be syntactically valid Python."""
    content = (FIXTURES_DIR / "simple.pym").read_text()
    ast.parse(content)


def test_with_multiple_externals_is_valid() -> None:
    """with_multiple_externals.pym should be valid Python."""
    content = (FIXTURES_DIR / "with_multiple_externals.pym").read_text()
    ast.parse(content)


def test_invalid_fixtures_are_valid_python() -> None:
    """Invalid .pym files should still be valid Python syntax."""
    for name in ["invalid_class.pym", "invalid_with.pym", "invalid_generator.pym"]:
        content = (FIXTURES_DIR / name).read_text()
        ast.parse(content)


def test_all_fixtures_exist() -> None:
    """All expected fixtures should exist."""
    expected = [
        "simple.pym",
        "with_multiple_externals.pym",
        "invalid_class.pym",
        "invalid_with.pym",
        "invalid_generator.pym",
        "missing_annotation.pym",
        "non_ellipsis_body.pym",
    ]

    for name in expected:
        path = FIXTURES_DIR / name
        assert path.exists(), f"Missing fixture: {name}"
