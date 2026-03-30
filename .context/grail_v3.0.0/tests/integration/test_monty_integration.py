"""Integration tests exercising the Grail API end-to-end.

These tests verify that Grail correctly wraps pydantic-monty for
basic execution, external functions, resource limits, type checking,
and error handling.
"""

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("pydantic_monty")

import grail


@pytest.mark.integration
async def test_basic_execution():
    """Test running simple inline code through grail.run()."""
    result = await grail.run("x = 1 + 2\nx")
    assert result == 3


@pytest.mark.integration
async def test_with_external_function(tmp_path):
    """Test loading and running a .pym file with external functions."""
    pym_path = tmp_path / "externals.pym"
    pym_path.write_text(
        """
from grail import external, Input

x: int = Input("x")

@external
async def double(n: int) -> int:
    ...

result = await double(x)
result
"""
    )

    script = grail.load(pym_path, grail_dir=None)

    async def double_impl(n: int) -> int:
        return n * 2

    result = await script.run(
        inputs={"x": 5},
        externals={"double": double_impl},
    )
    assert result == 10


@pytest.mark.integration
async def test_with_resource_limits(tmp_path):
    """Test execution with resource limits applied."""
    pym_path = tmp_path / "limited.pym"
    pym_path.write_text(
        """
from grail import Input

x: int = Input("x")

x
"""
    )

    script = grail.load(
        pym_path,
        limits=grail.Limits.strict(),
        grail_dir=None,
    )

    result = await script.run(inputs={"x": 1})
    assert result == 1


@pytest.mark.integration
def test_type_checking(tmp_path):
    """Test that check() validates type stubs correctly."""
    pym_path = tmp_path / "typecheck.pym"
    pym_path.write_text(
        """
from grail import external

@external
async def get_data(id: str) -> dict:
    ...

result = await get_data("test")
result
"""
    )

    script = grail.load(pym_path, grail_dir=None)
    check_result = script.check()
    assert check_result.valid is True


@pytest.mark.integration
async def test_error_handling():
    """Test that runtime errors are wrapped as ExecutionError."""
    with pytest.raises(grail.ExecutionError):
        await grail.run("y = undefined_variable")
