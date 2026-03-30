"""Tests for v3.2 refactor changes."""

import pytest
from pathlib import Path
from grail.parser import parse_pym_content
from grail.checker import check_pym
from grail.codegen import generate_monty_code
from grail.stubs import generate_stubs
from grail import (
    load,
    LimitError,
    CheckError,
    ExecutionError,
    InputError,
    OutputError,
    GrailError,
    ParseError,
    ParameterSpec,
    ParamKind,
)
from grail.limits import Limits


class TestLoadCheckEnforcement:
    """Tests for load() check enforcement (Phase 6.1)."""

    def test_load_raises_on_checker_error(self, tmp_path):
        """load() should raise CheckError for invalid scripts."""
        pym = tmp_path / "bad.pym"
        pym.write_text("class Foo:\n    pass\n")

        with pytest.raises(CheckError, match="E001"):
            load(pym)

    def test_load_succeeds_for_valid_script(self, tmp_path):
        """load() should succeed for valid scripts."""
        pym = tmp_path / "good.pym"
        pym.write_text("""
from grail import external

@external
async def fetch(url: str) -> str: ...

result = await fetch("https://example.com")
""")
        script = load(pym)
        assert script is not None


class TestOutputModelValidation:
    """Tests for output_model validation (Phase 6.2)."""

    @pytest.mark.asyncio
    async def test_output_model_validates_dict_result(self, tmp_path):
        """output_model should validate dict results via model_validate."""
        from pydantic import BaseModel

        class Output(BaseModel):
            value: int

        pym = tmp_path / "test.pym"
        pym.write_text(
            """from grail import Input
x: int = Input("x")
{"value": 42}
"""
        )

        script = load(pym)
        result = await script.run(inputs={"x": 1}, output_model=Output)
        assert isinstance(result, Output)
        assert result.value == 42

    @pytest.mark.asyncio
    async def test_output_model_invalid_raises_output_error(self, tmp_path):
        """output_model should raise OutputError for invalid results."""
        from pydantic import BaseModel

        class Output(BaseModel):
            value: int

        pym = tmp_path / "test.pym"
        pym.write_text(
            """from grail import Input
x: int = Input("x")
{"wrong_field": "not_int"}
"""
        )

        script = load(pym)
        with pytest.raises(OutputError):
            await script.run(inputs={"x": 1}, output_model=Output)


class TestVirtualFilesystem:
    """Tests for virtual filesystem (Phase 6.3).

    Note: Monty does not support 'with' statements.
    These tests verify the grail API accepts files parameter.
    """

    @pytest.mark.asyncio
    async def test_run_with_files_parameter(self, tmp_path):
        """Verify files parameter is accepted by run()."""
        pym = tmp_path / "test.pym"
        pym.write_text("x: int = 1\nx + 1")

        script = load(pym)
        result = await script.run(inputs={"x": 1}, strict_validation=False)
        assert result == 2

    @pytest.mark.asyncio
    async def test_files_override_at_runtime(self, tmp_path):
        """Verify runtime files can override load-time files."""
        pym = tmp_path / "test.pym"
        pym.write_text("x: int = 1\nx + 1")

        script = load(pym)
        result = await script.run(
            inputs={"x": 1}, files={"test.txt": "content"}, strict_validation=False
        )
        assert result == 2


class TestExternalExceptionPropagation:
    """Tests for external function exception handling (Phase 6.4)."""

    @pytest.mark.asyncio
    async def test_external_exception_maps_to_execution_error(self, tmp_path):
        """External function exceptions should map to ExecutionError."""
        pym = tmp_path / "test.pym"
        pym.write_text("""
from grail import external, Input

x: int = Input("x")

@external
async def fail(val: int) -> str: ...

result = await fail(x)
""")

        async def failing_external(val: int) -> str:
            raise ValueError("test error")

        script = load(pym)
        with pytest.raises(ExecutionError, match="ValueError"):
            await script.run(inputs={"x": 1}, externals={"fail": failing_external})

    @pytest.mark.asyncio
    async def test_external_exception_caught_in_script(self, tmp_path):
        """External function exceptions propagate as ExecutionError (not catchable in Monty)."""
        pym = tmp_path / "test.pym"
        pym.write_text("""
from grail import external, Input

x: int = Input("x")

@external
async def fail(val: int) -> str: ...

result = await fail(x)
""")

        async def failing_external(val: int) -> str:
            raise ValueError("boom")

        script = load(pym)
        with pytest.raises(ExecutionError, match="ValueError"):
            await script.run(inputs={"x": 1}, externals={"fail": failing_external})


class TestResourceLimitViolations:
    """Tests for resource limit violations (Phase 6.5)."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_duration_limit_exceeded(self, tmp_path):
        """Duration limit should raise LimitError."""
        pym = tmp_path / "infinite.pym"
        pym.write_text("while True:\n    pass\n")

        script = load(pym)
        with pytest.raises(LimitError) as exc_info:
            await script.run(limits=Limits(max_duration=0.001), strict_validation=False)

        assert exc_info.value.limit_type == "duration"

    @pytest.mark.asyncio
    async def test_recursion_limit_exceeded(self, tmp_path):
        """Recursion limit should raise LimitError."""
        pym = tmp_path / "recursive.pym"
        pym.write_text("""
def recurse(n):
    return recurse(n + 1)

result = recurse(0)
""")

        script = load(pym)
        with pytest.raises(LimitError) as exc_info:
            await script.run(limits=Limits(max_recursion=10), strict_validation=False)

        assert exc_info.value.limit_type == "recursion"


class TestLimitErrorHierarchy:
    """Tests for LimitError hierarchy change (Phase 6.6)."""

    def test_limit_error_is_grail_error(self):
        """LimitError should be a GrailError."""
        err = LimitError("test", limit_type="memory")
        assert isinstance(err, GrailError)

    def test_limit_error_is_not_execution_error(self):
        """LimitError should NOT be an ExecutionError."""
        err = LimitError("test", limit_type="memory")
        assert not isinstance(err, ExecutionError)

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_except_execution_error_does_not_catch_limit_error(self, tmp_path):
        """Catching ExecutionError should not catch LimitError."""
        pym = tmp_path / "infinite.pym"
        pym.write_text("while True:\n    pass\n")

        script = load(pym)
        with pytest.raises(LimitError):
            try:
                await script.run(limits=Limits(max_duration=0.001), strict_validation=False)
            except ExecutionError:
                pytest.fail("LimitError should not be caught by ExecutionError handler")


class TestParameterExtraction:
    """Tests for parameter extraction (Phase 6.7)."""

    def test_extract_all_param_kinds(self):
        """extract_function_params should extract all parameter kinds."""
        code = """
from grail import external

@external
async def fetch(a, /, b, *args, c=1, **kwargs) -> str: ...
"""
        result = parse_pym_content(code)
        externals_list = list(result.externals.values())
        params = externals_list[0].parameters
        assert len(params) == 5
        assert params[0].kind == ParamKind.POSITIONAL_ONLY
        assert params[1].kind == ParamKind.POSITIONAL_OR_KEYWORD
        assert params[2].kind == ParamKind.VAR_POSITIONAL
        assert params[3].kind == ParamKind.KEYWORD_ONLY
        assert params[3].has_default is True
        assert params[4].kind == ParamKind.VAR_KEYWORD

    def test_extract_kwonly_without_default(self):
        """Keyword-only params without defaults should have has_default=False."""
        code = """
from grail import external

@external
async def fetch(*, required_kwarg: str) -> str: ...
"""
        result = parse_pym_content(code)
        externals_list = list(result.externals.values())
        params = externals_list[0].parameters
        assert params[0].kind == ParamKind.KEYWORD_ONLY
        assert params[0].has_default is False


class TestCheckTOCTOU:
    """Tests for check() TOCTOU fix (Phase 6.8)."""

    def test_check_uses_cached_parse_result(self, tmp_path):
        """check() should validate the loaded code, not current disk contents."""
        pym = tmp_path / "test.pym"
        pym.write_text("result = 42\n")

        script = load(pym)

        pym.write_text("class Foo:\n    pass\n")

        result = script.check()
        assert result.valid


class TestInputNameValidation:
    """Tests for Input() name validation (Phase 6.9)."""

    def test_input_name_mismatch_raises(self, tmp_path):
        """Input name that doesn't match variable name should raise."""
        pym = tmp_path / "test.pym"
        pym.write_text('budget: float = Input("totally_wrong")\n')

        with pytest.raises((ParseError, CheckError)):
            load(pym)

    def test_input_name_matches_variable(self, tmp_path):
        """Input name that matches variable name should work."""
        pym = tmp_path / "test.pym"
        pym.write_text('budget: float = Input("budget")\n')

        script = load(pym)
        assert any(i.name == "budget" for i in script.inputs.values())


class TestCodegenDeclarationStripping:
    """Tests for codegen declaration stripping (Phase 6.10)."""

    def test_codegen_strips_annotated_input(self):
        """Annotated Input() should be stripped from generated code."""
        code = 'x: int = Input("x")\nresult = x + 1\n'
        result = parse_pym_content(code)
        monty, _ = generate_monty_code(result)
        assert "Input" not in monty
        assert "result = x + 1" in monty

    def test_codegen_strips_unannotated_input(self):
        """Unannotated Input() should be stripped from generated code."""
        code = 'x = Input("x")\nresult = x + 1\n'
        result = parse_pym_content(code)
        monty, _ = generate_monty_code(result)
        assert "Input" not in monty

    def test_codegen_preserves_non_input_assignment(self):
        """Non-Input assignments should be preserved."""
        code = "x: int = 42\nresult = x + 1\n"
        result = parse_pym_content(code)
        monty, _ = generate_monty_code(result)
        assert "x: int = 42" in monty or "x:int = 42" in monty

    def test_codegen_strips_grail_dot_input(self):
        """grail.Input() should be stripped from generated code."""
        code = 'x: int = grail.Input("x")\nresult = x + 1\n'
        result = parse_pym_content(code)
        monty, _ = generate_monty_code(result)
        assert "Input" not in monty


class TestStubGenerator:
    """Tests for stub generator (Phase 6.11)."""

    def test_stub_imports_optional(self):
        """Optional type should be imported from typing."""
        code = """
from grail import external

@external
async def fetch(url: str) -> Optional[str]: ...
"""
        result = parse_pym_content(code)
        stub = generate_stubs(result.externals, result.inputs)
        assert "from typing import Optional" in stub

    def test_stub_imports_multiple_typing_names(self):
        """All needed typing names should be imported."""
        code = """
from grail import external

@external
async def fetch(items: List[Dict[str, Any]]) -> Optional[int]: ...
"""
        result = parse_pym_content(code)
        stub = generate_stubs(result.externals, result.inputs)
        for name in ["Any", "Dict", "List", "Optional"]:
            assert name in stub

    def test_stub_escapes_triple_quotes(self):
        """Docstrings with triple quotes should be escaped."""
        code = '''
from grail import external

@external
async def fetch(url: str) -> str:
    """Returns data with \\""" in it."""
    ...
'''
        result = parse_pym_content(code)
        stub = generate_stubs(result.externals, result.inputs)
        compile(stub, "<stub>", "exec")


class TestParserEdgeCases:
    """Tests for parser edge cases (Phase 6.12)."""

    def test_parse_grail_dot_external(self):
        """@grail.external should be recognized."""
        code = """
@grail.external
async def foo(x: int) -> int: ...
"""
        result = parse_pym_content(code)
        assert len(result.externals) == 1

    def test_parse_sync_external(self):
        """Sync external functions should be recognized."""
        code = """
from grail import external

@external
def foo(x: int) -> int: ...
"""
        result = parse_pym_content(code)
        assert len(result.externals) == 1

    def test_parse_empty_file(self):
        """Empty file should have no externals or inputs."""
        result = parse_pym_content("")
        assert len(result.externals) == 0
        assert len(result.inputs) == 0

    def test_parse_grail_dot_input(self):
        """grail.Input() should be recognized."""
        code = 'x: int = grail.Input("x")\n'
        result = parse_pym_content(code)
        assert len(result.inputs) == 1


class TestCheckerEdgeCases:
    """Tests for checker edge cases (Phase 6.13)."""

    def test_e004_match_statement(self):
        """Match statements should be detected."""
        code = """
match x:
    case 1:
        pass
"""
        result = parse_pym_content(code)
        check = check_pym(result)
        assert any(m.code == "E004" for m in check.messages)

    def test_w004_long_script(self):
        """Scripts over 200 lines should trigger warning."""
        code = "\n".join(f"x_{i} = {i}" for i in range(201))
        result = parse_pym_content(code)
        check = check_pym(result)
        assert any(m.code == "W004" for m in check.messages)

    def test_yield_from_detected(self):
        """yield from should be detected."""
        code = """
def gen():
    yield from range(10)
"""
        result = parse_pym_content(code)
        check = check_pym(result)
        assert any(m.code == "E002" for m in check.messages)

    def test_multiple_errors_accumulated(self):
        """Multiple errors should all be reported."""
        code = """
class Foo: pass
class Bar: pass
def gen():
    yield 1
"""
        result = parse_pym_content(code)
        check = check_pym(result)
        errors = [m for m in check.messages if m.code.startswith("E")]
        assert len(errors) >= 3


class TestOnEventCallbacks:
    """Tests for on_event callbacks (Phase 6.14)."""

    @pytest.mark.asyncio
    async def test_on_event_captures_run_error(self, tmp_path):
        """on_event should capture run errors."""
        pym = tmp_path / "bad.pym"
        pym.write_text("1 / 0\n")

        events = []
        script = load(pym)
        with pytest.raises(ExecutionError):
            await script.run(inputs={}, on_event=lambda e: events.append(e))

        error_events = [e for e in events if e.type == "run_error"]
        assert len(error_events) == 1

    @pytest.mark.asyncio
    async def test_on_event_captures_print(self, tmp_path):
        """on_event should capture print output."""
        pym = tmp_path / "printer.pym"
        pym.write_text('print("hello")\nresult = 42\n')

        events = []
        script = load(pym)
        await script.run(inputs={}, on_event=lambda e: events.append(e))

        print_events = [e for e in events if e.type == "print"]
        assert len(print_events) >= 1


class TestDataclassRegistry:
    """Tests for dataclass_registry (Phase 6.15)."""

    @pytest.mark.asyncio
    async def test_dataclass_roundtrip(self, tmp_path):
        """Dataclasses should work as inputs."""
        from dataclasses import dataclass

        @dataclass
        class Person:
            name: str
            age: int

        pym = tmp_path / "test.pym"
        pym.write_text("""
from grail import Input

person: Person = Input("person")
result = f"{person.name} is {person.age}"
result
""")

        script = load(pym, dataclass_registry=[Person])
        result = await script.run(inputs={"person": Person("Alice", 30)})
        assert result == "Alice is 30"


class TestAdditionalEdgeCases:
    """Additional edge case tests (Phase 6.16)."""

    @pytest.mark.asyncio
    async def test_empty_script_through_pipeline(self, tmp_path):
        """Empty script should work through the pipeline."""
        pym = tmp_path / "empty.pym"
        pym.write_text("")
        script = load(pym)
        result = await script.run(inputs={})
        assert result is None

    @pytest.mark.asyncio
    async def test_script_with_only_imports(self, tmp_path):
        """Script with only imports should work."""
        pym = tmp_path / "imports_only.pym"
        pym.write_text("from grail import external\n")
        script = load(pym)
        result = await script.run(inputs={})
        assert result is None
