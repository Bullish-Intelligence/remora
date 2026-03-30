"""Core type definitions for grail."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class ParamKind(str, Enum):
    """Parameter kind enumeration."""

    POSITIONAL_ONLY = "positional-only"
    POSITIONAL_OR_KEYWORD = "positional-or-keyword"
    VAR_POSITIONAL = "var-positional"  # *args
    KEYWORD_ONLY = "keyword-only"
    VAR_KEYWORD = "var-keyword"  # **kwargs


@dataclass
class ParameterSpec:
    """Specification for a function parameter."""

    name: str
    type_annotation: str
    default: Any | None = None
    has_default: bool = False
    kind: ParamKind = ParamKind.POSITIONAL_OR_KEYWORD


@dataclass
class ExternalSpec:
    """Specification for an external function."""

    name: str
    is_async: bool
    parameters: list[ParameterSpec]
    return_type: str
    docstring: str | None
    lineno: int
    col_offset: int


@dataclass
class InputSpec:
    """Specification for an input variable."""

    name: str
    type_annotation: str
    default: Any | None
    required: bool
    lineno: int
    col_offset: int
    input_name: str | None = None


@dataclass
class ParseResult:
    """Result of parsing a .pym file."""

    externals: dict[str, ExternalSpec]
    inputs: dict[str, InputSpec]
    ast_module: ast.Module
    source_lines: list[str]
    file: str | None = None


@dataclass
class SourceMap:
    """Maps line numbers between .pym and monty_code.py."""

    monty_to_pym: dict[int, int] = field(default_factory=dict)
    pym_to_monty: dict[int, int] = field(default_factory=dict)

    def add_mapping(self, pym_line: int, monty_line: int) -> None:
        """Add a bidirectional line mapping."""

        if monty_line in self.monty_to_pym:
            return

        self.monty_to_pym[monty_line] = pym_line
        self.pym_to_monty.setdefault(pym_line, monty_line)


@dataclass
class CheckMessage:
    """A validation error or warning."""

    code: str
    lineno: int
    col_offset: int
    end_lineno: int | None
    end_col_offset: int | None
    severity: Literal["error", "warning"]
    message: str
    suggestion: str | None = None


@dataclass
class CheckResult:
    """Result of validation checks."""

    file: str
    valid: bool
    errors: list[CheckMessage]
    warnings: list[CheckMessage]
    info: dict[str, Any]

    @property
    def messages(self) -> list[CheckMessage]:
        """Combined list of all errors and warnings."""
        return self.errors + self.warnings


@dataclass
class ScriptEvent:
    """Structured event emitted during script execution.

    Event types:
    - "run_start": Script execution beginning
    - "run_complete": Script execution finished successfully
    - "run_error": Script execution failed
    - "print": Print output from inside the Monty sandbox
    - "check_start": Validation check beginning
    - "check_complete": Validation check finished
    """

    type: Literal[
        "run_start", "run_complete", "run_error", "print", "check_start", "check_complete"
    ]
    script_name: str
    timestamp: float
    text: str | None = None
    duration_ms: float | None = None
    error: str | None = None
    input_count: int | None = None
    external_count: int | None = None
    result_summary: str | None = None
