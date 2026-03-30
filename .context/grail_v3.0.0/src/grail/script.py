"""GrailScript - Main API for loading and executing .pym files."""

import asyncio
import functools
import logging
import warnings
from pathlib import Path
from typing import Any, Callable, Literal, NoReturn
import time
import re

logger = logging.getLogger(__name__)

import pydantic_monty

from grail._types import (
    ExternalSpec,
    InputSpec,
    CheckResult,
    CheckMessage,
    SourceMap,
    ScriptEvent,
    ParseResult,
)
from grail.parser import parse_pym_file
from grail.checker import check_pym
from grail.stubs import generate_stubs
from grail.codegen import generate_monty_code
from grail.artifacts import ArtifactsManager
from grail.limits import Limits
from grail.artifacts import ARTIFACTS_DIR_NAME
from grail.errors import (
    GrailError,
    InputError,
    ExternalError,
    ExecutionError,
    LimitError,
    OutputError,
    ParseError,
)
from pydantic import BaseModel


class GrailScript:
    """
    Main interface for loading and executing .pym files.

    This class encapsulates:
    - Parsed .pym file metadata
    - Generated Monty code and stubs
    - Validation results
    - Execution interface
    """

    def __init__(
        self,
        path: Path,
        externals: dict[str, ExternalSpec],
        inputs: dict[str, InputSpec],
        monty_code: str,
        stubs: str,
        source_map: SourceMap,
        source_lines: list[str],
        limits: Limits | None = None,
        files: dict[str, str | bytes] | None = None,
        environ: dict[str, str] | None = None,
        grail_dir: Path | None = None,
        dataclass_registry: list[type] | None = None,
    ):
        """
        Initialize GrailScript.

        Args:
            path: Path to original .pym file
            externals: External function specifications
            inputs: Input specifications
            monty_code: Generated Monty code
            stubs: Generated type stubs
            source_map: Line number mapping
            source_lines: .pym source lines
            limits: Resource limits
            files: Virtual filesystem files
            environ: Environment variables for os.getenv()
            grail_dir: Directory for artifacts (None disables)
            dataclass_registry: List of dataclass types for isinstance() checks
        """
        self.path = path
        self.name = path.stem
        self.externals = externals
        self.inputs = inputs
        self.monty_code = monty_code
        self.stubs = stubs
        self.source_map = source_map
        self.source_lines = source_lines
        self.limits = limits
        self.files = files
        self.environ = environ
        self.grail_dir = grail_dir
        self.dataclass_registry = dataclass_registry
        self._parse_result: ParseResult | None = None  # Set by load() for check() reuse

        # Initialize artifacts manager if grail_dir is set
        self._artifacts = ArtifactsManager(grail_dir) if grail_dir else None

    def check(self, on_event: Callable[..., None] | None = None) -> CheckResult:
        """
        Run validation checks on the script.

        Args:
            on_event: Optional callback for structured events

        Returns:
            CheckResult with errors, warnings, and info
        """
        logger.debug("Checking script %s", self.name)

        if on_event is not None:
            on_event(
                ScriptEvent(
                    type="check_start",
                    script_name=self.name,
                    timestamp=time.time(),
                )
            )

        # Use cached parse result for consistency with load-time
        # This avoids TOCTOU issues if file changed on disk
        parse_result = self._parse_result
        if parse_result is None:
            parse_result = parse_pym_file(self.path)

        check_result = check_pym(parse_result)
        check_result.file = str(self.path)

        # Run Monty type checker
        try:
            pydantic_monty.Monty(
                self.monty_code,
                script_name=f"{self.name}.pym",
                type_check=True,
                type_check_stubs=self.stubs,
                inputs=list(self.inputs.keys()),
                external_functions=list(self.externals.keys()),
            )
        except pydantic_monty.MontyTypingError as e:
            check_result.errors.append(
                CheckMessage(
                    code="E100",
                    lineno=0,
                    col_offset=0,
                    end_lineno=None,
                    end_col_offset=None,
                    severity="error",
                    message=f"Type error: {str(e)}",
                    suggestion="Fix the type error indicated above",
                )
            )
            check_result.valid = False

        # Write check results to artifacts if enabled
        if self._artifacts:
            try:
                self._artifacts.write_script_artifacts(
                    self.name,
                    self.stubs,
                    self.monty_code,
                    check_result,
                    self.externals,
                    self.inputs,
                )
            except OSError as e:
                import logging

                logging.getLogger(__name__).warning("Failed to write artifacts: %s", e)

        if on_event is not None:
            on_event(
                ScriptEvent(
                    type="check_complete",
                    script_name=self.name,
                    timestamp=time.time(),
                    result_summary=f"{'valid' if check_result.valid else 'invalid'}: {len(check_result.errors)} errors, {len(check_result.warnings)} warnings",
                )
            )

        return check_result

    def _validate_inputs(self, inputs: dict[str, Any], strict: bool = True) -> None:
        """
        Validate provided inputs against declarations.

        Args:
            inputs: Runtime input values
            strict: If True, raise errors for undeclared inputs. If False, warn.

        Raises:
            InputError: Missing required inputs or (in strict mode) extra inputs
        """
        # Check for missing required inputs
        for name, spec in self.inputs.items():
            if spec.required and name not in inputs:
                raise InputError(
                    f"Missing required input: '{name}' (type: {spec.type_annotation})",
                    input_name=name,
                )

        # Check for extra inputs
        for name in inputs:
            if name not in self.inputs:
                if strict:
                    raise InputError(
                        f"Extra input '{name}' not declared in script",
                        input_name=name,
                    )
                else:
                    warnings.warn(
                        f"Extra input '{name}' not declared in script",
                        stacklevel=2,
                    )

    def _validate_externals(self, externals: dict[str, Callable], strict: bool = True) -> None:
        """
        Validate that provided externals match declarations.

        Args:
            externals: Runtime external function implementations
            strict: If True, raise errors for undeclared externals. If False, warn.

        Raises:
            ExternalError: Missing externals or (in strict mode) extra externals
        """
        # Check for missing externals
        for name in self.externals:
            if name not in externals:
                raise ExternalError(f"Missing external function: '{name}'", function_name=name)

        # Check for extra externals
        for name in externals:
            if name not in self.externals:
                if strict:
                    raise ExternalError(
                        f"Extra external '{name}' not declared in script",
                        function_name=name,
                    )
                else:
                    warnings.warn(
                        f"Extra external '{name}' not declared in script",
                        stacklevel=2,
                    )

    def _prepare_monty_limits(self, override_limits: Limits | None) -> dict[str, Any]:
        """
        Merge load-time and run-time limits into a Monty-native dict.

        Falls back to Limits.default() if no limits are provided anywhere.
        """
        base = self.limits
        if base is None:
            if override_limits is None:
                return Limits.default().to_monty()
            return override_limits.to_monty()
        if override_limits is None:
            return base.to_monty()
        return base.merge(override_limits).to_monty()

    def _prepare_monty_os_access(
        self,
        override_files: dict[str, str | bytes] | None,
        override_environ: dict[str, str] | None,
    ):
        """Prepare OSAccess for Monty with files and environment variables.

        Args:
            override_files: Runtime file overrides
            override_environ: Runtime environment variable overrides

        Returns:
            OSAccess object or None
        """
        files = override_files if override_files is not None else self.files
        environ = override_environ if override_environ is not None else self.environ

        if not files and not environ:
            return None

        memory_files = None
        if files:
            memory_files = []
            for path, content in files.items():
                memory_files.append(pydantic_monty.MemoryFile(path, content))

        return pydantic_monty.OSAccess(
            files=memory_files,
            environ=environ,
        )

    def _handle_run_error(
        self,
        error: Exception,
        start_time: float,
        captured_output: list[str],
    ) -> NoReturn:
        """Map a runtime error, fire events, write logs, and re-raise."""
        duration_ms = (time.time() - start_time) * 1000
        mapped_error = self._map_error_to_pym(error)

        logger.warning("Script execution failed: %s", mapped_error)

        # Fire event
        on_event = getattr(self, "_current_on_event", None)
        if on_event is not None:
            on_event(
                ScriptEvent(
                    type="run_error",
                    script_name=self.name,
                    timestamp=time.time(),
                    duration_ms=duration_ms,
                    error=str(mapped_error),
                )
            )

        # Write error log
        if self._artifacts:
            stdout_text = "".join(captured_output)
            self._artifacts.write_run_log(
                self.name,
                stdout=stdout_text,
                stderr=str(mapped_error),
                duration_ms=duration_ms,
                success=False,
            )

        raise mapped_error from error

    def _map_error_to_pym(self, error: Exception) -> GrailError:
        """
        Map Monty error to .pym file line numbers.

        Uses structured traceback data from MontyRuntimeError when available,
        falling back to message parsing for other error types.

        Args:
            error: Original error from Monty

        Returns:
            GrailError (ExecutionError, LimitError, or ParseError) with mapped line numbers
        """
        # Preserve original exception type from MontyError.exception() if available
        original_exception_type = None
        if hasattr(error, "exception") and callable(error.exception):
            original = error.exception()
            if original is not None:
                original_exception_type = type(original).__name__

        error_msg = str(error)
        if original_exception_type:
            error_msg = f"{original_exception_type}: {error_msg}"

        # 1. Check exception type first (most reliable)
        if hasattr(error, "limit_type"):
            # Monty limit errors should carry structured data
            return LimitError(error_msg, limit_type=error.limit_type)

        # 2. Extract line number from structured traceback if available
        lineno = None
        col_offset = None
        source_context = None
        if hasattr(error, "traceback") and callable(error.traceback):
            tb = error.traceback()
            if tb:
                frame = tb[-1]
                monty_line = frame.line
                lineno = self.source_map.monty_to_pym.get(monty_line)
                # Do NOT fall back to monty_line — it's meaningless to users

                # Use Frame source_line for context
                if hasattr(frame, "source_line") and frame.source_line:
                    source_context = frame.source_line

        # 3. Regex fallback — only for well-structured patterns
        if lineno is None:
            match = re.search(r"(?:^|,\s*)line\s+(\d+)(?:\s*,|\s*$)", error_msg)
            if match:
                raw_line = int(match.group(1))
                lineno = self.source_map.monty_to_pym.get(raw_line)
                # Still don't fall back — None is better than a wrong number

        # 4. Limit detection — require exception type OR "limit" + keyword
        error_msg_lower = error_msg.lower()
        if "limit" in error_msg_lower or "exceeded" in error_msg_lower:
            limit_type = None
            if "memory" in error_msg_lower:
                limit_type = "memory"
            elif "duration" in error_msg_lower or "timeout" in error_msg_lower:
                limit_type = "duration"
            elif "recursion" in error_msg_lower:
                limit_type = "recursion"
            elif "allocation" in error_msg_lower:
                limit_type = "allocations"
            if limit_type:
                return LimitError(error_msg, limit_type=limit_type)

        # 5. Map MontySyntaxError to ParseError
        if type(error).__name__ == "MontySyntaxError":
            return ParseError(error_msg, lineno=lineno)

        # 6. Default to ExecutionError
        if source_context is None:
            source_context = "\n".join(self.source_lines) if self.source_lines else None
        return ExecutionError(
            error_msg,
            lineno=lineno,
            col_offset=col_offset,
            source_context=source_context,
            suggestion=None,
        )

    async def run(
        self,
        inputs: dict[str, Any] | None = None,
        externals: dict[str, Callable] | None = None,
        output_model: type[BaseModel] | None = None,
        files: dict[str, str | bytes] | None = None,
        environ: dict[str, str] | None = None,
        limits: Limits | None = None,
        print_callback: Callable[[Literal["stdout"], str], None] | None = None,
        on_event: Callable[[ScriptEvent], None] | None = None,
        strict_validation: bool = True,
    ) -> Any:
        """
        Execute the script in Monty.

        Args:
            inputs: Input values
            externals: External function implementations
            output_model: Optional Pydantic model for output validation
            files: Override files from load()
            environ: Override environment variables from load()
            limits: Override limits from load()
            print_callback: Optional callback for print() output from the script.
                Signature: (stream: Literal["stdout"], text: str) -> None
            on_event: Optional callback for structured lifecycle events.
            strict_validation: If True (default), raise errors for undeclared
                inputs or externals. If False, only warn.

        Returns:
            Result of script execution

        Raises:
            InputError: Missing or invalid inputs
            ExternalError: Missing external functions
            ExecutionError: Monty runtime error
            OutputError: Output validation failed
        """

        inputs = inputs or {}
        externals = externals or {}
        monty_inputs = inputs if self.inputs else None

        captured_output: list[str] = []

        def _monty_print_callback(stream: str, text: str) -> None:
            captured_output.append(text)
            if print_callback is not None:
                print_callback(stream, text)
            if on_event is not None:
                on_event(
                    ScriptEvent(
                        type="print",
                        script_name=self.name,
                        timestamp=time.time(),
                        text=text,
                    )
                )

        if on_event is not None:
            on_event(
                ScriptEvent(
                    type="run_start",
                    script_name=self.name,
                    timestamp=time.time(),
                    input_count=len(inputs),
                    external_count=len(externals),
                )
            )

        logger.debug(
            "Running script %s with %d inputs, %d externals", self.name, len(inputs), len(externals)
        )

        # Validate inputs and externals
        self._validate_inputs(inputs, strict=strict_validation)
        self._validate_externals(externals, strict=strict_validation)

        # Prepare Monty configuration
        parsed_limits = self._prepare_monty_limits(limits)
        os_access = self._prepare_monty_os_access(files, environ)

        # Create Monty instance - catch type errors during construction
        try:
            monty = pydantic_monty.Monty(
                self.monty_code,
                script_name=f"{self.name}.pym",
                type_check=True,
                type_check_stubs=self.stubs,
                inputs=list(self.inputs.keys()),
                external_functions=list(self.externals.keys()),
                dataclass_registry=self.dataclass_registry,
            )
        except pydantic_monty.MontyTypingError as e:
            # Convert type errors to ExecutionError
            raise ExecutionError(
                f"Type checking failed: {str(e)}",
                lineno=None,
                source_context=None,
                suggestion="Fix type errors in your code",
            ) from e

        # Execute
        start_time = time.time()
        self._current_on_event = on_event
        try:
            result = await pydantic_monty.run_monty_async(
                monty,
                inputs=monty_inputs,
                external_functions=externals,
                os=os_access,
                limits=parsed_limits,
                print_callback=_monty_print_callback,
            )
        except Exception as e:
            self._handle_run_error(e, start_time, captured_output)

        duration_ms = (time.time() - start_time) * 1000
        stdout_text = "".join(captured_output)

        # Write success log
        if self._artifacts:
            self._artifacts.write_run_log(
                self.name,
                stdout=stdout_text,
                stderr="",
                duration_ms=duration_ms,
                success=True,
            )

        if on_event is not None:
            on_event(
                ScriptEvent(
                    type="run_complete",
                    script_name=self.name,
                    timestamp=time.time(),
                    duration_ms=duration_ms,
                    result_summary=f"{type(result).__name__}",
                )
            )

        # Validate output if model provided
        if output_model is not None:
            try:
                if isinstance(result, dict):
                    result = output_model.model_validate(result)
                else:
                    result = output_model.model_validate(result, from_attributes=True)
            except Exception as e:
                raise OutputError(f"Output validation failed: {e}", validation_errors=e) from e

        return result

    def run_sync(
        self,
        inputs: dict[str, Any] | None = None,
        externals: dict[str, Callable] | None = None,
        **kwargs,
    ) -> Any:
        """
        Synchronous wrapper around run().

        Args:
            inputs: Input values
            externals: External function implementations
            **kwargs: Additional arguments for run()

        Returns:
            Result of script execution

        Raises:
            RuntimeError: If called from within an async context where a new
                event loop cannot be created. Use `await script.run()` instead.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run(inputs, externals, **kwargs))
        else:
            raise RuntimeError(
                "run_sync() cannot be used inside an async context "
                "(e.g., Jupyter, FastAPI). Use 'await script.run()' instead."
            )


def load(
    path: str | Path,
    limits: Limits | None = None,
    files: dict[str, str | bytes] | None = None,
    environ: dict[str, str] | None = None,
    grail_dir: str | Path | None = ARTIFACTS_DIR_NAME,
    dataclass_registry: list[type] | None = None,
) -> GrailScript:
    """
    Load and parse a .pym file.

    Args:
        path: Path to .pym file
        limits: Resource limits
        files: Virtual filesystem files
        environ: Environment variables for os.getenv()
        grail_dir: Directory for artifacts (None disables)
        dataclass_registry: List of dataclass types for isinstance() checks

    Returns:
        GrailScript instance

    Raises:
        FileNotFoundError: If file doesn't exist
        ParseError: If file has syntax errors
        CheckError: If declarations are malformed
    """
    from grail.errors import CheckError

    path = Path(path)

    logger.debug("Loading script from %s", path)

    # Parse the file
    parse_result = parse_pym_file(path)

    # Run validation checks
    check_result = check_pym(parse_result)
    check_result.file = str(path)

    # Raise if there are errors
    errors = [msg for msg in check_result.messages if msg.code.startswith("E")]
    if errors:
        error_summary = "; ".join(f"{m.code}: {m.message} (line {m.lineno})" for m in errors)
        raise CheckError(f"Script validation failed with {len(errors)} error(s): {error_summary}")

    # Generate stubs
    stubs = generate_stubs(parse_result.externals, parse_result.inputs)

    # Generate Monty code
    monty_code, source_map = generate_monty_code(parse_result)

    # Setup grail_dir
    grail_dir_path = Path(grail_dir) if grail_dir else None

    # Write artifacts
    if grail_dir_path:
        try:
            artifacts = ArtifactsManager(grail_dir_path)
            artifacts.write_script_artifacts(
                path.stem,
                stubs,
                monty_code,
                check_result,
                parse_result.externals,
                parse_result.inputs,
            )
        except OSError as e:
            import logging

            logging.getLogger(__name__).warning("Failed to write artifacts: %s", e)

    script = GrailScript(
        path=path,
        externals=parse_result.externals,
        inputs=parse_result.inputs,
        monty_code=monty_code,
        stubs=stubs,
        source_map=source_map,
        source_lines=parse_result.source_lines,
        limits=limits,
        files=files,
        environ=environ,
        grail_dir=grail_dir_path,
        dataclass_registry=dataclass_registry,
    )
    script._parse_result = parse_result  # Cache for check() reuse
    return script


async def run(
    code: str,
    *,
    inputs: dict[str, Any] | None = None,
    limits: Limits | None = None,
    environ: dict[str, str] | None = None,
    print_callback: Callable[[Literal["stdout"], str], None] | None = None,
) -> Any:
    """Run a Monty script from source code.

    This is a simple escape hatch for quick execution. For production use,
    prefer grail.load() which provides full validation and error mapping.

    Args:
        code: Monty code to execute
        inputs: Input values
        limits: Resource limits (defaults to Limits.default())
        environ: Environment variables for os.getenv()
        print_callback: Optional callback for print() output from the script.
            Signature: (stream: Literal["stdout"], text: str) -> None

    Returns:
        Result of code execution
    """
    input_names = list(inputs.keys()) if inputs else []
    monty = pydantic_monty.Monty(code, inputs=input_names)

    parsed_limits = (limits or Limits.default()).to_monty()

    os_access = None
    if environ:
        os_access = pydantic_monty.OSAccess(environ=environ)

    try:
        return await pydantic_monty.run_monty_async(
            monty,
            inputs=inputs or None,
            limits=parsed_limits or None,
            os=os_access,
            print_callback=print_callback,
        )
    except pydantic_monty.MontyRuntimeError as e:
        error_msg = str(e)
        raise ExecutionError(
            error_msg,
            lineno=None,
            source_context=None,
            suggestion=None,
        ) from e


def run_sync(
    code: str,
    *,
    inputs: dict[str, Any] | None = None,
    limits: Limits | None = None,
    print_callback: Callable[[Literal["stdout"], str], None] | None = None,
) -> Any:
    """Synchronous wrapper for inline Monty code execution.

    Args:
        code: Monty code to execute
        inputs: Input values
        limits: Resource limits
        print_callback: Optional callback for print() output

    Returns:
        Result of code execution

    Raises:
        RuntimeError: If called from within an async context.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run(code, inputs=inputs, limits=limits, print_callback=print_callback))
    else:
        raise RuntimeError(
            "run_sync() cannot be used inside an async context. Use 'await grail.run()' instead."
        )
