"""Test .pym file parser."""

from pathlib import Path

import pytest

from grail.errors import CheckError, ParseError
from grail.parser import parse_pym_content, parse_pym_file

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_parse_simple_pym() -> None:
    """Parse simple.pym fixture."""
    result = parse_pym_file(FIXTURES_DIR / "simple.pym")

    assert "double" in result.externals
    ext = result.externals["double"]
    assert ext.is_async is True
    assert ext.return_type == "int"
    assert len(ext.parameters) == 1
    assert ext.parameters[0].name == "n"
    assert ext.parameters[0].type_annotation == "int"

    assert "x" in result.inputs
    inp = result.inputs["x"]
    assert inp.type_annotation == "int"
    assert inp.required is True


def test_parse_multiple_externals() -> None:
    """Parse fixture with multiple externals."""
    result = parse_pym_file(FIXTURES_DIR / "with_multiple_externals.pym")

    assert "get_team" in result.externals
    assert "get_expenses" in result.externals

    assert "budget" in result.inputs
    assert "department" in result.inputs

    dept = result.inputs["department"]
    assert dept.required is False
    assert dept.default == "Engineering"


def test_missing_type_annotation_raises() -> None:
    """Missing type annotation should NOT raise during parsing - handled by checker."""
    content = """
from grail import external

@external
def bad_func(x):
    ...
"""
    # Parser should now succeed (lenient)
    result = parse_pym_content(content)
    assert "bad_func" in result.externals
    # But the checker should catch this as E006
    from grail.checker import check_pym

    check_result = check_pym(result)
    assert not check_result.valid
    assert any(e.code == "E006" for e in check_result.errors)


def test_missing_return_type_raises() -> None:
    """Missing return type should NOT raise during parsing - handled by checker."""
    content = """
from grail import external

@external
def bad_func(x: int):
    ...
"""
    result = parse_pym_content(content)
    assert "bad_func" in result.externals
    from grail.checker import check_pym

    check_result = check_pym(result)
    assert not check_result.valid
    assert any(e.code == "E006" for e in check_result.errors)


def test_non_ellipsis_body_raises() -> None:
    """Non-ellipsis body should NOT raise during parsing - handled by checker."""
    content = """
from grail import external

@external
def bad_func(x: int) -> int:
    return x * 2
"""
    result = parse_pym_content(content)
    assert "bad_func" in result.externals
    from grail.checker import check_pym

    check_result = check_pym(result)
    assert not check_result.valid
    assert any(e.code == "E007" for e in check_result.errors)


def test_input_without_annotation_raises() -> None:
    """Input without type annotation should NOT raise during parsing - handled by checker."""
    content = """
from grail import Input

x = Input("x")
"""
    result = parse_pym_content(content)
    assert "x" in result.inputs
    from grail.checker import check_pym

    check_result = check_pym(result)
    assert not check_result.valid
    assert any(e.code == "E008" for e in check_result.errors)


def test_syntax_error_raises_parse_error() -> None:
    """Invalid Python syntax should raise ParseError."""
    content = "def bad syntax here"

    with pytest.raises(ParseError):
        parse_pym_content(content)


def test_extract_docstring() -> None:
    """Should extract function docstrings."""
    content = """
from grail import external

@external
async def fetch_data(url: str) -> dict:
    '''Fetch data from URL.'''
    ...
"""
    result = parse_pym_content(content)

    assert "fetch_data" in result.externals
    assert result.externals["fetch_data"].docstring == "Fetch data from URL."


def test_function_with_defaults() -> None:
    """Should handle function parameters with defaults."""
    content = """
from grail import external

@external
def process(x: int, y: int = 10) -> int:
    ...
"""
    result = parse_pym_content(content)

    func = result.externals["process"]
    assert len(func.parameters) == 2
    assert func.parameters[0].name == "x"
    assert func.parameters[0].default is None
    assert func.parameters[1].name == "y"
    assert func.parameters[1].default == "Constant(value=10)"


def test_nested_external_not_extracted() -> None:
    """An @external function inside another function should NOT be extracted."""
    content = """
from grail import external


def outer():
    @external
    def inner(x: int) -> str: ...

    return inner(5)
"""
    result = parse_pym_content(content)

    assert "inner" not in result.externals


def test_nested_input_not_extracted() -> None:
    """An Input() call inside a function should NOT be extracted."""
    content = """
from grail import Input


def compute():
    x: int = Input("x")
    return x * 2
"""
    result = parse_pym_content(content)

    assert "x" not in result.inputs
