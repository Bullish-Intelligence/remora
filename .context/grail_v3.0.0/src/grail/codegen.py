"""Code generator - transforms .pym to Monty-compatible code."""

import ast
import copy
import logging
from grail._types import ParseResult, SourceMap
from grail.errors import GrailError

logger = logging.getLogger(__name__)


class GrailDeclarationStripper(ast.NodeTransformer):
    """
    AST transformer that removes grail-specific declarations.

    Removes:
    - from grail import ... statements
    - @external decorated function definitions
    - Input() assignment statements

    Preserves:
    - All executable code
    - from typing import ... statements
    """

    def __init__(self, externals: set[str], inputs: set[str]):
        self.externals = externals  # Set of external function names
        self.inputs = inputs  # Set of input variable names

    def _is_input_call(self, node: ast.expr | None) -> bool:
        """Check if an expression is an Input() or grail.Input() call."""
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Name) and func.id == "Input":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "Input":
            return True
        return False

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.ImportFrom | None:
        """Remove 'from grail import ...' statements.

        Note: 'from typing import ...' statements are preserved because Monty
        supports typing module imports (e.g., Dict, List, Optional).
        """
        if node.module == "grail":
            return None  # Remove this node
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef | None:
        """Remove @external function definitions."""
        if node.name in self.externals:
            return None  # Remove this node
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef | None:
        """Remove @external async function definitions."""
        if node.name in self.externals:
            return None
        return node

    def visit_Assign(self, node: ast.Assign) -> ast.AST | None:
        """Strip Input() assignments without annotations."""
        if self._is_input_call(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in self.inputs:
                    return None  # Remove this node entirely
        return self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST | None:
        """Remove Input() assignment statements."""
        if isinstance(node.target, ast.Name) and node.target.id in self.inputs:
            if self._is_input_call(node.value):
                return None  # Remove this node entirely
        return self.generic_visit(node)


def build_source_map(transformed_ast: ast.Module, generated_code: str) -> SourceMap:
    """
    Build line number mapping between .pym and generated code.

    Strategy: Walk both ASTs at the statement level (not BFS over all nodes),
    matching statements by their sequential position. This is robust because
    ast.unparse() preserves statement order even when node structure changes
    during the unparse/re-parse round-trip.

    Args:
        transformed_ast: AST after stripping declarations (retains original line numbers)
        generated_code: Generated Monty code string

    Returns:
        SourceMap with line mappings
    """
    source_map = SourceMap()
    generated_ast = ast.parse(generated_code)

    def _collect_line_numbers(module: ast.Module) -> list[int]:
        """Collect line numbers for all statement-level nodes."""
        result = []
        for node in ast.walk(module):
            if isinstance(node, ast.stmt) and not isinstance(node, ast.Module):
                lineno = getattr(node, "lineno", None)
                if lineno is not None:
                    result.append(lineno)
        return result

    original_lines = _collect_line_numbers(transformed_ast)
    generated_lines = _collect_line_numbers(generated_ast)

    # Map each generated line to its original .pym line
    for orig_line, gen_line in zip(original_lines, generated_lines):
        source_map.add_mapping(pym_line=orig_line, monty_line=gen_line)

    return source_map


def generate_monty_code(parse_result: ParseResult) -> tuple[str, SourceMap]:
    """
    Generate Monty-compatible code from parsed .pym file.

    NOTE: Generated Monty code loses all comments, blank lines, and original
    formatting. This is inherent to ast.unparse(). The source map preserves
    line number mapping for error reporting.

    Args:
        parse_result: Result from parse_pym_file()

    Returns:
        Tuple of (monty_code, source_map)
    """
    logger.debug("Generating Monty code")
    # Get sets of names to remove
    external_names = set(parse_result.externals.keys())
    input_names = set(parse_result.inputs.keys())

    # Transform AST (deepcopy to avoid mutating original)
    stripper = GrailDeclarationStripper(external_names, input_names)
    transformed = stripper.visit(copy.deepcopy(parse_result.ast_module))

    # Fix missing locations after transformation
    ast.fix_missing_locations(transformed)

    # Generate code from transformed AST
    monty_code = ast.unparse(transformed)

    # Validate generated code is syntactically valid
    try:
        ast.parse(monty_code)
    except SyntaxError as exc:
        raise GrailError(
            f"Code generation produced invalid Python: {exc}. "
            "This is a bug in grail — please report it."
        )

    # Build source map
    source_map = build_source_map(transformed, monty_code)

    return monty_code, source_map
