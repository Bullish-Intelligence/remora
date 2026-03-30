"""Test error hierarchy."""

import pytest

from grail.errors import (
    CheckError,
    ExecutionError,
    ExternalError,
    GrailError,
    InputError,
    LimitError,
    OutputError,
    ParseError,
)


def test_error_hierarchy() -> None:
    """All errors should inherit from GrailError."""
    assert issubclass(ParseError, GrailError)
    assert issubclass(CheckError, GrailError)
    assert issubclass(InputError, GrailError)
    assert issubclass(ExternalError, GrailError)
    assert issubclass(ExecutionError, GrailError)
    assert issubclass(LimitError, GrailError)
    assert issubclass(OutputError, GrailError)


def test_limit_error_is_grail_error() -> None:
    """LimitError should be a subclass of GrailError."""
    err = LimitError("test", limit_type="memory")
    assert isinstance(err, GrailError)


def test_limit_error_is_not_execution_error() -> None:
    """LimitError should NOT be a subclass of ExecutionError."""
    err = LimitError("test", limit_type="memory")
    assert not isinstance(err, ExecutionError)


def test_parse_error_formatting() -> None:
    """ParseError should format with line numbers."""
    err = ParseError("unexpected token", lineno=10, col_offset=5)
    assert "line 10" in str(err)
    assert "unexpected token" in str(err)


def test_execution_error_shows_context() -> None:
    """ExecutionError with source_context should display surrounding lines."""
    source = "x = 1\ny = 2\nz = undefined\nw = 4\nv = 5"
    err = ExecutionError(
        message="NameError: name 'undefined' is not defined",
        lineno=3,
        source_context=source,
    )
    formatted = str(err)
    assert "> " in formatted
    assert "3 |" in formatted
    assert "z = undefined" in formatted
    assert "x = 1" in formatted
    assert "w = 4" in formatted


def test_execution_error_without_context() -> None:
    """ExecutionError without source_context should still format cleanly."""
    err = ExecutionError(message="Something failed", lineno=5)
    formatted = str(err)
    assert "Line 5" in formatted
    assert "Something failed" in formatted
    assert "> " not in formatted


def test_limit_error_has_limit_type() -> None:
    """LimitError should carry the limit_type field."""
    err = LimitError(message="Memory limit exceeded", limit_type="memory")
    assert err.limit_type == "memory"
    assert "Memory limit exceeded" in str(err)


def test_limit_error_without_limit_type() -> None:
    """LimitError with no limit_type should default to None."""
    err = LimitError(message="Unknown limit exceeded")
    assert err.limit_type is None
