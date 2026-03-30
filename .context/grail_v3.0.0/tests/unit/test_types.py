"""Test core type definitions."""

from grail._types import (
    CheckMessage,
    CheckResult,
    ExternalSpec,
    InputSpec,
    ParameterSpec,
    ParseResult,
    SourceMap,
)


def test_external_spec_creation() -> None:
    spec = ExternalSpec(
        name="test_func",
        is_async=True,
        parameters=[ParameterSpec("x", "int", None)],
        return_type="str",
        docstring="Test function",
        lineno=1,
        col_offset=0,
    )
    assert spec.name == "test_func"
    assert spec.is_async is True


def test_source_map_bidirectional() -> None:
    smap = SourceMap()
    smap.add_mapping(pym_line=10, monty_line=5)

    assert smap.pym_to_monty[10] == 5
    assert smap.monty_to_pym[5] == 10


def test_check_message_creation() -> None:
    msg = CheckMessage(
        code="E001",
        lineno=10,
        col_offset=4,
        end_lineno=10,
        end_col_offset=10,
        severity="error",
        message="Test error",
        suggestion="Fix it",
    )
    assert msg.code == "E001"
    assert msg.severity == "error"


def test_check_result_creation() -> None:
    result = CheckResult(
        file="script.pym",
        valid=True,
        errors=[],
        warnings=[],
        info={"externals": 1},
    )
    assert result.valid is True
    assert result.file == "script.pym"


def test_parse_result_creation() -> None:
    parse_result = ParseResult(
        externals={},
        inputs={},
        ast_module=__import__("ast").Module(body=[]),
        source_lines=["x = 1"],
    )
    assert parse_result.source_lines == ["x = 1"]


def test_input_spec_creation() -> None:
    spec = InputSpec(
        name="value",
        type_annotation="int",
        default=None,
        required=True,
        lineno=1,
        col_offset=0,
    )
    assert spec.required is True
