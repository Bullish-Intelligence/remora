"""Parser for .pym files - extracts externals and inputs from AST."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any

from grail._types import ExternalSpec, InputSpec, ParameterSpec, ParseResult
from grail.errors import ParseError

logger = logging.getLogger(__name__)


def get_type_annotation_str(node: ast.expr | None, lenient: bool = False) -> str:
    """Convert AST type annotation node to string.

    Args:
        node: AST annotation node.
        lenient: If True, return "<missing>" instead of raising ParseError.

    Returns:
        String representation of type (e.g., "int", "dict[str, Any]").

    Raises:
        ParseError: If annotation is missing or invalid (only when lenient=False).
    """
    if node is None:
        if lenient:
            return "<missing>"
        raise ParseError("Missing type annotation")

    return ast.unparse(node)


def _get_annotation(node: ast.expr | None) -> str:
    """Convert AST annotation node to string."""
    if node is None:
        return "<missing>"
    return ast.unparse(node)


def extract_function_params(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ParameterSpec]:
    """Extract parameter specifications from function definition.

    Handles all parameter kinds: positional-only, positional-or-keyword,
    var-positional (*args), keyword-only, and var-keyword (**kwargs).

    Args:
        func_node: Function definition AST node.

    Returns:
        List of parameter specifications.
    """
    from grail._types import ParamKind

    params: list[ParameterSpec] = []
    args = func_node.args

    # Defaults are right-aligned: if there are 3 args and 1 default,
    # the default applies to the 3rd arg.
    num_posonly = len(args.posonlyargs)
    num_regular = len(args.args)
    num_pos_defaults = len(args.defaults)
    # defaults apply to the LAST N of (posonlyargs + args)
    total_positional = num_posonly + num_regular
    first_default_idx = total_positional - num_pos_defaults

    # Positional-only arguments
    for i, arg in enumerate(args.posonlyargs):
        global_idx = i
        has_default = global_idx >= first_default_idx
        default_val = None
        if has_default:
            default_val = ast.dump(args.defaults[global_idx - first_default_idx])
        params.append(
            ParameterSpec(
                name=arg.arg,
                type_annotation=_get_annotation(arg.annotation),
                has_default=has_default,
                default=default_val,
                kind=ParamKind.POSITIONAL_ONLY,
            )
        )

    # Regular positional-or-keyword arguments
    for i, arg in enumerate(args.args):
        if arg.arg == "self":
            continue

        global_idx = num_posonly + i
        has_default = global_idx >= first_default_idx
        default_val = None
        if has_default:
            default_val = ast.dump(args.defaults[global_idx - first_default_idx])
        params.append(
            ParameterSpec(
                name=arg.arg,
                type_annotation=_get_annotation(arg.annotation),
                has_default=has_default,
                default=default_val,
                kind=ParamKind.POSITIONAL_OR_KEYWORD,
            )
        )

    # *args
    if args.vararg:
        params.append(
            ParameterSpec(
                name=args.vararg.arg,
                type_annotation=_get_annotation(args.vararg.annotation),
                has_default=False,
                kind=ParamKind.VAR_POSITIONAL,
            )
        )

    # Keyword-only arguments (kw_defaults aligns 1:1 with kwonlyargs)
    for i, arg in enumerate(args.kwonlyargs):
        kw_default = args.kw_defaults[i]  # None if no default
        params.append(
            ParameterSpec(
                name=arg.arg,
                type_annotation=_get_annotation(arg.annotation),
                has_default=kw_default is not None,
                default=ast.dump(kw_default) if kw_default is not None else None,
                kind=ParamKind.KEYWORD_ONLY,
            )
        )

    # **kwargs
    if args.kwarg:
        params.append(
            ParameterSpec(
                name=args.kwarg.arg,
                type_annotation=_get_annotation(args.kwarg.annotation),
                has_default=False,
                kind=ParamKind.VAR_KEYWORD,
            )
        )

    return params


def extract_externals(module: ast.Module) -> dict[str, ExternalSpec]:
    """Extract external function specifications from AST.

    Looks for functions decorated with @external.

    Args:
        module: Parsed AST module.

    Returns:
        Dictionary mapping function names to ExternalSpec.

    Raises:
        ParseError: If external declarations are malformed.
    """
    externals: dict[str, ExternalSpec] = {}

    for node in module.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        has_external = False
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "external":
                has_external = True
                break
            if isinstance(decorator, ast.Attribute) and decorator.attr == "external":
                has_external = True
                break

        if not has_external:
            continue

        params = extract_function_params(node)
        docstring = ast.get_docstring(node)

        externals[node.name] = ExternalSpec(
            name=node.name,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            parameters=params,
            return_type=get_type_annotation_str(node.returns, lenient=True),
            docstring=docstring,
            lineno=node.lineno,
            col_offset=node.col_offset,
        )

    return externals


def _is_input_call(node: ast.expr | None) -> bool:
    """Check if an expression is Input() or grail.Input()."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id == "Input":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "Input":
        return True
    return False


def _extract_input_from_call(
    call_node: ast.Call, var_name: str, lineno: int, col_offset: int, type_annotation: str
) -> InputSpec:
    """Extract InputSpec from an Input() call node."""
    input_name = None
    if call_node.args:
        if isinstance(call_node.args[0], ast.Constant):
            input_name = call_node.args[0].value

    if input_name is not None and input_name != var_name:
        raise ParseError(
            f"Input name '{input_name}' doesn't match variable name '{var_name}' "
            f'at line {lineno}. Use Input("{var_name}") or omit the name argument.'
        )

    default = None
    has_default = False
    for kw in call_node.keywords:
        if kw.arg == "default":
            has_default = True
            default = ast.literal_eval(kw.value) if isinstance(kw.value, ast.Constant) else None

    return InputSpec(
        name=var_name,
        type_annotation=type_annotation,
        default=default,
        required=default is None,
        lineno=lineno,
        col_offset=col_offset,
        input_name=input_name,
    )


def extract_inputs(module: ast.Module) -> dict[str, InputSpec]:
    """Extract input specifications from AST.

    Looks for assignments like: x: int = Input("x").

    Args:
        module: Parsed AST module.

    Returns:
        Dictionary mapping input names to InputSpec.

    Raises:
        ParseError: If input declarations are malformed.
    """
    inputs: dict[str, InputSpec] = {}

    for node in module.body:
        if isinstance(node, ast.AnnAssign):
            if not _is_input_call(node.value):
                continue

            if node.annotation is None:
                annotation_str = "<missing>"
            else:
                annotation_str = get_type_annotation_str(node.annotation)

            if not isinstance(node.target, ast.Name):
                raise ParseError(
                    "Input() must be assigned to a simple variable name",
                    lineno=node.lineno,
                )

            var_name = node.target.id

            if not node.value.args:
                raise ParseError(
                    f"Input() call for '{var_name}' missing name argument",
                    lineno=node.lineno,
                )

            inputs[var_name] = _extract_input_from_call(
                node.value, var_name, node.lineno, node.col_offset, annotation_str
            )

        elif isinstance(node, ast.Assign):
            if not _is_input_call(node.value):
                continue

            if not isinstance(node.targets[0], ast.Name):
                raise ParseError(
                    "Input() must be assigned to a simple variable name",
                    lineno=node.lineno,
                )

            var_name = node.targets[0].id
            inputs[var_name] = _extract_input_from_call(
                node.value, var_name, node.lineno, node.col_offset, "<missing>"
            )

    return inputs


def parse_pym_file(path: Path) -> ParseResult:
    """Parse a .pym file from disk.

    Args:
        path: Path to .pym file.

    Returns:
        ParseResult with externals, inputs, AST, and source lines.

    Raises:
        FileNotFoundError: If file doesn't exist.
        ParseError: If file has syntax errors.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Script file not found: {path}")
    source = path.read_text(encoding="utf-8")
    return parse_pym_content(source, filename=str(path))


def parse_pym_content(content: str, filename: str = "<string>") -> ParseResult:
    """Parse .pym content from string (useful for testing).

    Args:
        content: .pym file content.
        filename: Optional filename for error messages.

    Returns:
        ParseResult.

    Raises:
        ParseError: If content has syntax errors or declarations are malformed.
    """
    logger.debug("Parsing pym content: %s", filename)
    source_lines = content.splitlines()

    try:
        module = ast.parse(content, filename=filename)
    except SyntaxError as exc:
        raise ParseError(exc.msg, lineno=exc.lineno, col_offset=exc.offset) from exc

    externals = extract_externals(module)
    inputs = extract_inputs(module)

    return ParseResult(
        externals=externals,
        inputs=inputs,
        ast_module=module,
        source_lines=source_lines,
        file=filename,
    )
