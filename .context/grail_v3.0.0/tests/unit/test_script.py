"""Test GrailScript class."""

import pytest
from pathlib import Path

from grail.script import load, GrailScript
from grail.errors import InputError, ExternalError

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_load_pym_file():
    """Should load and parse .pym file."""
    script = load(FIXTURES_DIR / "simple.pym", grail_dir=None)

    assert script.name == "simple"
    assert "double" in script.externals
    assert "x" in script.inputs
    assert len(script.monty_code) > 0
    assert len(script.stubs) > 0


def test_check_returns_result():
    """Should return CheckResult."""
    script = load(FIXTURES_DIR / "simple.pym", grail_dir=None)
    result = script.check()

    assert result.valid is True
    assert result.file == str(FIXTURES_DIR / "simple.pym")


def test_validate_inputs_missing_required():
    """Should raise InputError for missing required input."""
    script = load(FIXTURES_DIR / "simple.pym", grail_dir=None)

    with pytest.raises(InputError, match="Missing required input"):
        script._validate_inputs({})


def test_validate_inputs_extra_input_warns():
    """Should warn for extra inputs."""
    script = load(FIXTURES_DIR / "simple.pym", grail_dir=None)

    with pytest.warns(UserWarning, match="Extra input"):
        script._validate_inputs({"x": 1, "extra": 2}, strict=False)


def test_validate_externals_missing():
    """Should raise ExternalError for missing external."""
    script = load(FIXTURES_DIR / "simple.pym", grail_dir=None)

    with pytest.raises(ExternalError, match="Missing external function"):
        script._validate_externals({})


def test_validate_externals_extra_warns():
    """Should warn for extra externals."""
    script = load(FIXTURES_DIR / "simple.pym", grail_dir=None)

    with pytest.warns(UserWarning, match="Extra external"):
        script._validate_externals({"double": lambda x: x * 2, "extra": lambda: None}, strict=False)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_run_simple_script():
    """Should execute simple script."""
    pytest.importorskip("pydantic_monty")

    script = load(FIXTURES_DIR / "simple.pym", grail_dir=None)

    async def double_impl(n: int) -> int:
        return n * 2

    result = await script.run(inputs={"x": 5}, externals={"double": double_impl})

    assert result == 10


@pytest.mark.integration
def test_run_sync():
    """Should execute script synchronously."""
    pytest.importorskip("pydantic_monty")

    script = load(FIXTURES_DIR / "simple.pym", grail_dir=None)

    async def double_impl(n: int) -> int:
        return n * 2

    result = script.run_sync(inputs={"x": 5}, externals={"double": double_impl})

    assert result == 10


def test_load_with_limits():
    """Should accept Limits parameter."""
    from grail.limits import Limits

    script = load(
        FIXTURES_DIR / "simple.pym",
        limits=Limits(max_memory="8mb"),
        grail_dir=None,
    )

    assert isinstance(script.limits, Limits)
    assert script.limits.max_memory == 8 * 1024 * 1024


def test_load_with_files():
    """Should accept files parameter."""
    script = load(FIXTURES_DIR / "simple.pym", files={"/data/test.txt": "content"}, grail_dir=None)

    assert script.files == {"/data/test.txt": "content"}


def test_load_creates_artifacts(tmp_path):
    """Should create artifacts in grail_dir."""
    script = load(FIXTURES_DIR / "simple.pym", grail_dir=tmp_path / ".grail")

    artifacts_dir = tmp_path / ".grail" / "simple"
    assert artifacts_dir.exists()
    assert (artifacts_dir / "stubs.pyi").exists()
    assert (artifacts_dir / "monty_code.py").exists()
    assert (artifacts_dir / "check.json").exists()


def test_map_error_to_pym_uses_source_map():
    """_map_error_to_pym should translate Monty line numbers to .pym line numbers."""
    from grail._types import SourceMap
    from grail.errors import ExecutionError

    source_map = SourceMap()
    source_map.add_mapping(pym_line=10, monty_line=3)

    script = GrailScript(
        path=FIXTURES_DIR / "simple.pym",
        externals={},
        inputs={},
        monty_code="",
        stubs="",
        source_map=source_map,
        source_lines=["x = 1"],
        limits=None,
        files=None,
        grail_dir=None,
    )

    error = RuntimeError("line 3, something")
    mapped = script._map_error_to_pym(error)

    assert isinstance(mapped, ExecutionError)
    assert mapped.lineno == 10
