"""Test grail declarations (external, Input)."""

from grail._external import external
from grail._input import Input


def test_external_decorator_is_noop() -> None:
    """External decorator should not modify function behavior - it's a pure identity."""

    @external
    def dummy(x: int) -> int:
        return x + 1

    # external is a pure identity function - no attributes are set
    assert not hasattr(dummy, "__grail_external__")
    assert dummy(2) == 3


def test_input_returns_default() -> None:
    """Input should return the default value."""
    result = Input("test_var", default="default_value")
    assert result == "default_value"


def test_input_without_default_returns_none() -> None:
    """Input without default should return None."""
    result = Input("test_var")
    assert result is None


def test_can_import_from_grail() -> None:
    """Should be able to import from grail package."""
    from grail import Input as public_input
    from grail import external as public_external

    assert public_external is not None
    assert public_input is not None
