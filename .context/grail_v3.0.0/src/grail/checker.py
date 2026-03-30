"""Validation checker for Monty compatibility."""

from __future__ import annotations

import ast
import logging

from grail._types import CheckMessage, CheckResult, ParseResult

logger = logging.getLogger(__name__)

ALLOWED_MODULES: set[str] = {
    "grail",
    "typing",
    "__future__",
}


class MontyCompatibilityChecker(ast.NodeVisitor):
    """AST visitor that detects Monty-incompatible Python features.

    Errors detected:
    - E001: Class definitions
    - E002: Generators (yield/yield from)
    - E003: with statements
    - E004: match statements
    - E005: Forbidden imports
    - E009: global statements
    - E010: nonlocal statements
    - E011: del statements
    - E012: Lambda expressions
    """

    def __init__(self, source_lines: list[str]):
        self.errors: list[CheckMessage] = []
        self.warnings: list[CheckMessage] = []
        self.source_lines = source_lines
        self.features_used: set[str] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Detect class definitions (not supported in Monty)."""
        self.errors.append(
            CheckMessage(
                code="E001",
                lineno=node.lineno,
                col_offset=node.col_offset,
                end_lineno=node.end_lineno,
                end_col_offset=node.end_col_offset,
                severity="error",
                message="Class definitions are not supported in Monty",
                suggestion="Remove the class or refactor to use functions and dicts",
            )
        )
        self.generic_visit(node)

    def visit_Yield(self, node: ast.Yield) -> None:
        """Detect yield expressions (generators not supported)."""
        self.errors.append(
            CheckMessage(
                code="E002",
                lineno=node.lineno,
                col_offset=node.col_offset,
                end_lineno=node.end_lineno,
                end_col_offset=node.end_col_offset,
                severity="error",
                message="Generator functions (yield) are not supported in Monty",
                suggestion="Refactor to return a list or use async iteration",
            )
        )
        self.generic_visit(node)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        """Detect yield from expressions."""
        self.errors.append(
            CheckMessage(
                code="E002",
                lineno=node.lineno,
                col_offset=node.col_offset,
                end_lineno=node.end_lineno,
                end_col_offset=node.end_col_offset,
                severity="error",
                message="Generator functions (yield from) are not supported in Monty",
                suggestion="Refactor to return a list",
            )
        )
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        """Detect with statements (not supported)."""
        self.errors.append(
            CheckMessage(
                code="E003",
                lineno=node.lineno,
                col_offset=node.col_offset,
                end_lineno=node.end_lineno,
                end_col_offset=node.end_col_offset,
                severity="error",
                message="'with' statements are not supported in Monty",
                suggestion="Use try/finally instead, or make file operations external functions",
            )
        )
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        """Detect match statements (not supported yet)."""
        self.errors.append(
            CheckMessage(
                code="E004",
                lineno=node.lineno,
                col_offset=node.col_offset,
                end_lineno=node.end_lineno,
                end_col_offset=node.end_col_offset,
                severity="error",
                message="'match' statements are not supported in Monty yet",
                suggestion="Use if/elif/else instead",
            )
        )
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """Detect import statements (only grail, typing, __future__ allowed)."""
        for alias in node.names:
            root_module = alias.name.split(".")[0]
            if root_module not in ALLOWED_MODULES:
                self.errors.append(
                    CheckMessage(
                        code="E005",
                        lineno=node.lineno,
                        col_offset=node.col_offset,
                        end_lineno=node.end_lineno,
                        end_col_offset=node.end_col_offset,
                        severity="error",
                        message=f"Import '{alias.name}' is not allowed in Monty",
                        suggestion=(
                            "Only 'from grail import ...', 'from typing import ...', "
                            "and 'from __future__ import ...' are allowed"
                        ),
                    )
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Detect from...import statements."""
        if node.module is not None and node.module not in ALLOWED_MODULES:
            module_name = node.module
            self.errors.append(
                CheckMessage(
                    code="E005",
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    end_lineno=node.end_lineno,
                    end_col_offset=node.end_col_offset,
                    severity="error",
                    message=f"Import from '{module_name}' is not allowed in Monty",
                    suggestion=(
                        "Only 'from grail import ...', 'from typing import ...', "
                        "and 'from __future__ import ...' are allowed"
                    ),
                )
            )
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Track async/await usage."""
        is_external = any(
            (isinstance(decorator, ast.Name) and decorator.id == "external")
            or (isinstance(decorator, ast.Attribute) and decorator.attr == "external")
            for decorator in node.decorator_list
        )
        # External async functions are excluded from feature tracking because
        # they are stripped during code generation and don't represent actual
        # async usage within the Monty sandbox. Only user-defined async code
        # counts as a Monty feature dependency.
        if not is_external:
            self.features_used.add("async_await")
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        """Track for-loop usage."""
        self.features_used.add("for_loop")
        self.generic_visit(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        """Track list comprehension usage."""
        self.features_used.add("list_comprehension")
        self.generic_visit(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        """Track dict comprehension usage."""
        self.features_used.add("dict_comprehension")
        self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        """Track f-string usage."""
        self.features_used.add("f_string")
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        """Detect global statements (not supported in Monty)."""
        self.errors.append(
            CheckMessage(
                code="E009",
                lineno=node.lineno,
                col_offset=node.col_offset,
                end_lineno=node.end_lineno,
                end_col_offset=node.end_col_offset,
                severity="error",
                message="'global' statements are not supported in Monty",
                suggestion="Avoid using global - restructure your code to use function parameters and return values",
            )
        )
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        """Detect nonlocal statements (not supported in Monty)."""
        self.errors.append(
            CheckMessage(
                code="E010",
                lineno=node.lineno,
                col_offset=node.col_offset,
                end_lineno=node.end_lineno,
                end_col_offset=node.end_col_offset,
                severity="error",
                message="'nonlocal' statements are not supported in Monty",
                suggestion="Avoid using nonlocal - restructure your code to use function parameters and return values",
            )
        )
        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete) -> None:
        """Detect del statements (not supported in Monty)."""
        self.errors.append(
            CheckMessage(
                code="E011",
                lineno=node.lineno,
                col_offset=node.col_offset,
                end_lineno=node.end_lineno,
                end_col_offset=node.end_col_offset,
                severity="error",
                message="'del' statements are not supported in Monty",
                suggestion="Avoid using del - restructure your code to not need variable deletion",
            )
        )
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        """Detect lambda expressions (not supported in Monty)."""
        self.errors.append(
            CheckMessage(
                code="E012",
                lineno=node.lineno,
                col_offset=node.col_offset,
                end_lineno=node.end_lineno,
                end_col_offset=node.end_col_offset,
                severity="error",
                message="Lambda expressions are not supported in Monty",
                suggestion="Use a regular function definition (def) instead",
            )
        )
        self.generic_visit(node)


def check_declarations(parse_result: ParseResult) -> list[CheckMessage]:
    """Check that @external and Input() declarations are well-formed.

    Errors detected:
    - E006: Missing type annotations on @external parameters or return type
    - E007: @external with non-ellipsis body
    - E008: Input() without type annotation

    Args:
        parse_result: Result of parsing a .pym file.

    Returns:
        List of error messages.
    """
    errors: list[CheckMessage] = []

    for ext in parse_result.externals.values():
        if ext.return_type == "<missing>":
            errors.append(
                CheckMessage(
                    code="E006",
                    lineno=ext.lineno,
                    col_offset=ext.col_offset,
                    end_lineno=None,
                    end_col_offset=None,
                    severity="error",
                    message=f"External function '{ext.name}' missing return type annotation",
                    suggestion=f"Add a return type annotation: async def {ext.name}(...) -> ReturnType:",
                )
            )
        for param in ext.parameters:
            if param.type_annotation == "<missing>":
                errors.append(
                    CheckMessage(
                        code="E006",
                        lineno=ext.lineno,
                        col_offset=ext.col_offset,
                        end_lineno=None,
                        end_col_offset=None,
                        severity="error",
                        message=f"Parameter '{param.name}' in external function '{ext.name}' missing type annotation",
                        suggestion=f"Add a type annotation: {param.name}: type",
                    )
                )

    for node in parse_result.ast_module.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        has_external = any(
            (isinstance(d, ast.Name) and d.id == "external")
            or (isinstance(d, ast.Attribute) and d.attr == "external")
            for d in node.decorator_list
        )
        if not has_external:
            continue

        body_start = 0
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            body_start = 1

        remaining = node.body[body_start:]
        is_valid_body = (
            len(remaining) == 1
            and isinstance(remaining[0], ast.Expr)
            and isinstance(remaining[0].value, ast.Constant)
            and remaining[0].value.value is Ellipsis
        )
        if not is_valid_body:
            errors.append(
                CheckMessage(
                    code="E007",
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    end_lineno=node.end_lineno,
                    end_col_offset=node.end_col_offset,
                    severity="error",
                    message=f"External function '{node.name}' body must be '...' (Ellipsis), not actual code",
                    suggestion="Replace the function body with: ...",
                )
            )

    for inp in parse_result.inputs.values():
        if inp.type_annotation == "<missing>":
            errors.append(
                CheckMessage(
                    code="E008",
                    lineno=inp.lineno,
                    col_offset=inp.col_offset,
                    end_lineno=None,
                    end_col_offset=None,
                    severity="error",
                    message=f"Input '{inp.name}' missing type annotation",
                    suggestion=f'Add a type annotation: {inp.name}: type = Input("{inp.name}")',
                )
            )

    return errors


def check_for_warnings(parse_result: ParseResult) -> list[CheckMessage]:
    """Check for warning conditions (non-blocking issues).

    Warnings:
    - W001: Bare dict/list as return value
    - W002: Unused @external function
    - W003: Unused Input() variable
    - W004: Very long script (>200 lines)

    Args:
        parse_result: Result of parsing a .pym file.

    Returns:
        List of warning messages.
    """
    warnings: list[CheckMessage] = []
    module = parse_result.ast_module

    if module.body:
        last_stmt = module.body[-1]
        if isinstance(last_stmt, ast.Expr) and isinstance(last_stmt.value, (ast.Dict, ast.List)):
            warnings.append(
                CheckMessage(
                    code="W001",
                    lineno=last_stmt.lineno,
                    col_offset=last_stmt.col_offset,
                    end_lineno=last_stmt.end_lineno,
                    end_col_offset=last_stmt.end_col_offset,
                    severity="warning",
                    message=(
                        "Bare dict/list as return value — consider assigning to a variable for clarity"
                    ),
                    suggestion="result = {...}; result",
                )
            )

    if len(parse_result.source_lines) > 200:
        warnings.append(
            CheckMessage(
                code="W004",
                lineno=1,
                col_offset=0,
                end_lineno=None,
                end_col_offset=None,
                severity="warning",
                message=(
                    "Script is "
                    f"{len(parse_result.source_lines)} lines long (>200) — may indicate too much logic in sandbox"
                ),
                suggestion="Consider breaking into smaller scripts or moving logic to external functions",
            )
        )

    # W002: Unused @external functions
    external_names = set(parse_result.externals.keys())
    input_names = set(parse_result.inputs.keys())

    referenced_names: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            referenced_names.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            referenced_names.add(node.attr)

    for name, spec in parse_result.externals.items():
        if name not in referenced_names:
            warnings.append(
                CheckMessage(
                    code="W002",
                    lineno=spec.lineno,
                    col_offset=spec.col_offset,
                    end_lineno=None,
                    end_col_offset=None,
                    severity="warning",
                    message=f"External function '{name}' is declared but never called",
                    suggestion=f"Remove the @external declaration for '{name}' if it's not needed",
                )
            )

    # W003: Unused Input() variables
    for name, spec in parse_result.inputs.items():
        if name not in referenced_names:
            warnings.append(
                CheckMessage(
                    code="W003",
                    lineno=spec.lineno,
                    col_offset=spec.col_offset,
                    end_lineno=None,
                    end_col_offset=None,
                    severity="warning",
                    message=f"Input '{name}' is declared but never referenced",
                    suggestion=f"Remove the Input() declaration for '{name}' if it's not needed",
                )
            )

    return warnings


def check_pym(parse_result: ParseResult) -> CheckResult:
    """Run all validation checks on parsed .pym file.

    Args:
        parse_result: Result from parse_pym_file().

    Returns:
        CheckResult with errors, warnings, and info.
    """
    filename = parse_result.file or "<unknown>"
    logger.debug("Checking script: %s", filename)

    checker = MontyCompatibilityChecker(parse_result.source_lines)
    checker.visit(parse_result.ast_module)

    declaration_errors = check_declarations(parse_result)
    all_errors = checker.errors + declaration_errors

    warnings = check_for_warnings(parse_result)
    warnings.extend(checker.warnings)

    info = {
        "externals_count": len(parse_result.externals),
        "inputs_count": len(parse_result.inputs),
        "lines_of_code": len(parse_result.source_lines),
        "monty_features_used": sorted(checker.features_used),
    }

    return CheckResult(
        file=parse_result.file or "<unknown>",
        valid=len(all_errors) == 0,
        errors=all_errors,
        warnings=warnings,
        info=info,
    )
