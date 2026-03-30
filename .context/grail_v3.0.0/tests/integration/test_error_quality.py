"""Integration tests for error and warning quality."""

import pytest

from grail.checker import check_pym
from grail.parser import parse_pym_content


@pytest.mark.integration
def test_check_error_includes_line_number():
    """Check errors should include the line number of the problem."""
    content = """\
from grail import external

class Forbidden:
    pass
"""
    parsed = parse_pym_content(content, filename="test.pym")
    result = check_pym(parsed)

    assert not result.valid
    assert result.errors[0].lineno == 3


@pytest.mark.integration
def test_check_warning_includes_suggestion():
    """Checker warnings should include actionable suggestions."""
    content = """\
from grail import Input

value: int = Input("value")

{"value": value}
"""
    parsed = parse_pym_content(content, filename="warning.pym")
    result = check_pym(parsed)

    assert result.valid
    assert result.warnings
    assert result.warnings[0].suggestion is not None
