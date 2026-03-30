"""Test Monty compatibility checker."""

from pathlib import Path

from grail.checker import check_pym
from grail.parser import parse_pym_content, parse_pym_file

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_valid_pym_passes() -> None:
    """Valid .pym files should pass all checks."""
    result = parse_pym_file(FIXTURES_DIR / "simple.pym")
    check_result = check_pym(result)

    assert check_result.valid is True
    assert len(check_result.errors) == 0


def test_class_definition_detected() -> None:
    """Class definitions should be detected as E001."""
    result = parse_pym_file(FIXTURES_DIR / "invalid_class.pym")
    check_result = check_pym(result)

    assert check_result.valid is False
    assert any(error.code == "E001" for error in check_result.errors)
    assert any("Class definitions" in error.message for error in check_result.errors)


def test_with_statement_detected() -> None:
    """'with' statements should be detected as E003."""
    result = parse_pym_file(FIXTURES_DIR / "invalid_with.pym")
    check_result = check_pym(result)

    assert check_result.valid is False
    assert any(error.code == "E003" for error in check_result.errors)


def test_generator_detected() -> None:
    """Generators should be detected as E002."""
    result = parse_pym_file(FIXTURES_DIR / "invalid_generator.pym")
    check_result = check_pym(result)

    assert check_result.valid is False
    assert any(error.code == "E002" for error in check_result.errors)


def test_forbidden_import_detected() -> None:
    """Forbidden imports should be detected as E005."""
    content = """
import json

data = json.loads('{}')
"""
    result = parse_pym_content(content)
    check_result = check_pym(result)

    assert check_result.valid is False
    assert any(error.code == "E005" for error in check_result.errors)
    assert any("json" in error.message for error in check_result.errors)


def test_typing_import_allowed() -> None:
    """Imports from typing should be allowed."""
    content = """
from typing import Any, Dict

x: Dict[str, Any] = {}
"""
    result = parse_pym_content(content)
    check_result = check_pym(result)

    assert not any(error.code == "E005" for error in check_result.errors)


def test_info_collection() -> None:
    """Should collect info about the script."""
    result = parse_pym_file(FIXTURES_DIR / "with_multiple_externals.pym")
    check_result = check_pym(result)

    assert check_result.info["externals_count"] == 2
    assert check_result.info["inputs_count"] == 2
    assert check_result.info["lines_of_code"] > 0
    assert "for_loop" in check_result.info["monty_features_used"]


def test_bare_dict_warning() -> None:
    """Bare dict as final expression should warn."""
    content = """
from grail import external, Input

x: int = Input("x")

{"result": x * 2}
"""
    result = parse_pym_content(content)
    check_result = check_pym(result)

    assert any(warning.code == "W001" for warning in check_result.warnings)


def test_external_async_not_tracked_as_feature() -> None:
    """External async functions should not count toward async_await feature tracking."""
    content = """\
from grail import external

@external
async def fetch(url: str) -> str: ...

result = "hello"
"""
    parsed = parse_pym_content(content)
    result = check_pym(parsed)

    assert "async_await" not in result.info.get("monty_features_used", [])


def test_e006_missing_return_type() -> None:
    """E006: External function missing return type annotation."""
    content = """from grail import external
@external
async def fetch(id: int):
    ...
"""
    parse_result = parse_pym_content(content)
    result = check_pym(parse_result)
    assert not result.valid
    assert any(e.code == "E006" for e in result.errors)


def test_e006_missing_param_annotation() -> None:
    """E006: External function parameter missing type annotation."""
    content = """from grail import external
@external
async def fetch(id) -> str:
    ...
"""
    parse_result = parse_pym_content(content)
    result = check_pym(parse_result)
    assert not result.valid
    assert any(e.code == "E006" for e in result.errors)


def test_e007_non_ellipsis_body() -> None:
    """E007: External function with actual code body."""
    content = """from grail import external
@external
async def fetch(id: int) -> str:
    return "hello"
"""
    parse_result = parse_pym_content(content)
    result = check_pym(parse_result)
    assert not result.valid
    assert any(e.code == "E007" for e in result.errors)


def test_e008_input_missing_annotation() -> None:
    """E008: Input() without type annotation."""
    content = """from grail import Input
x = Input("x")
"""
    parse_result = parse_pym_content(content)
    result = check_pym(parse_result)
    assert not result.valid
    assert any(e.code == "E008" for e in result.errors)


def test_w002_unused_external() -> None:
    """W002: Declared @external function never called."""
    content = """from grail import external

@external
async def fetch(id: int) -> str:
    ...

# Never calls fetch()
x = 42
x
"""
    parse_result = parse_pym_content(content)
    result = check_pym(parse_result)
    assert any(w.code == "W002" for w in result.warnings)


def test_w003_unused_input() -> None:
    """W003: Declared Input() variable never referenced."""
    content = """from grail import Input

x: int = Input("x")
y: int = Input("y")

# Only uses x, not y
x + 1
"""
    parse_result = parse_pym_content(content)
    result = check_pym(parse_result)
    assert any(w.code == "W003" and "y" in w.message for w in result.warnings)
    assert not any(w.code == "W003" and "x" in w.message for w in result.warnings)
