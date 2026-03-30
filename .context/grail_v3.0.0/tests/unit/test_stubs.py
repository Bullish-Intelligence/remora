"""Test type stub generation."""

from grail._types import ExternalSpec, InputSpec, ParameterSpec
from grail.stubs import generate_stubs


def test_generate_simple_stub() -> None:
    """Generate stub for simple external function."""
    externals = {
        "double": ExternalSpec(
            name="double",
            is_async=True,
            parameters=[ParameterSpec("n", "int", None)],
            return_type="int",
            docstring="Double a number.",
            lineno=1,
            col_offset=0,
        )
    }
    inputs = {
        "x": InputSpec(
            name="x",
            type_annotation="int",
            default=None,
            required=True,
            lineno=1,
            col_offset=0,
        )
    }

    stub = generate_stubs(externals, inputs)

    assert "x: int" in stub
    assert "async def double(n: int) -> int:" in stub
    assert "Double a number." in stub
    assert "..." in stub


def test_stub_with_any_import() -> None:
    """Stub should import Any when needed."""
    externals = {
        "fetch": ExternalSpec(
            name="fetch",
            is_async=True,
            parameters=[ParameterSpec("url", "str", None)],
            return_type="dict[str, Any]",
            docstring=None,
            lineno=1,
            col_offset=0,
        )
    }

    stub = generate_stubs(externals, {})

    assert "from typing import Any" in stub
    assert "dict[str, Any]" in stub


def test_stub_with_defaults() -> None:
    """Stub should include default parameter values."""
    externals = {
        "process": ExternalSpec(
            name="process",
            is_async=False,
            parameters=[
                ParameterSpec("x", "int", None),
                ParameterSpec("y", "int", 10),
            ],
            return_type="int",
            docstring=None,
            lineno=1,
            col_offset=0,
        )
    }

    stub = generate_stubs(externals, {})

    assert "def process(x: int, y: int = 10) -> int:" in stub


def test_multiple_inputs_and_externals() -> None:
    """Stub should handle multiple declarations."""
    externals = {
        "func1": ExternalSpec("func1", True, [], "None", None, 1, 0),
        "func2": ExternalSpec("func2", False, [], "str", None, 2, 0),
    }
    inputs = {
        "a": InputSpec("a", "int", None, True, 1, 0),
        "b": InputSpec("b", "str", "default", False, 2, 0),
    }

    stub = generate_stubs(externals, inputs)

    assert "a: int" in stub
    assert "b: str" in stub
    assert "async def func1() -> None:" in stub
    assert "def func2() -> str:" in stub


def test_any_detection_does_not_match_substring() -> None:
    """Type annotations like 'Company' should not trigger an Any import."""
    externals = {
        "get_company": ExternalSpec(
            name="get_company",
            is_async=False,
            parameters=[],
            return_type="Company",
            docstring=None,
            lineno=1,
            col_offset=0,
        )
    }

    result = generate_stubs(externals=externals, inputs={})

    assert "from typing import Any" not in result


def test_any_detection_matches_actual_any() -> None:
    """A return type of 'Any' should trigger the Any import."""
    externals = {
        "get_data": ExternalSpec(
            name="get_data",
            is_async=False,
            parameters=[],
            return_type="Any",
            docstring=None,
            lineno=1,
            col_offset=0,
        )
    }

    result = generate_stubs(externals=externals, inputs={})

    assert "from typing import Any" in result
