"""Test artifacts manager."""

import json
from pathlib import Path

from grail.artifacts import ArtifactsManager
from grail._types import CheckResult, ExternalSpec, InputSpec, ParameterSpec


def test_creates_directory_structure(tmp_path):
    """Should create .grail/<script>/ directory structure."""
    mgr = ArtifactsManager(tmp_path / ".grail")

    externals = {
        "test_func": ExternalSpec(
            name="test_func",
            is_async=True,
            parameters=[ParameterSpec("x", "int", None)],
            return_type="str",
            docstring="Test",
            lineno=1,
            col_offset=0,
        )
    }
    inputs = {
        "test_input": InputSpec(
            name="test_input",
            type_annotation="int",
            default=None,
            required=True,
            lineno=1,
            col_offset=0,
        )
    }
    check_result = CheckResult(file="test.pym", valid=True, errors=[], warnings=[], info={})

    mgr.write_script_artifacts("test", "# stubs", "# code", check_result, externals, inputs)

    script_dir = tmp_path / ".grail" / "test"
    assert script_dir.exists()
    assert (script_dir / "stubs.pyi").exists()
    assert (script_dir / "monty_code.py").exists()
    assert (script_dir / "check.json").exists()
    assert (script_dir / "externals.json").exists()
    assert (script_dir / "inputs.json").exists()


def test_write_run_log(tmp_path):
    """Should write run.log with execution details."""
    mgr = ArtifactsManager(tmp_path / ".grail")

    mgr.write_run_log("test", stdout="Hello world", stderr="", duration_ms=42.5, success=True)

    log_path = tmp_path / ".grail" / "test" / "run.log"
    assert log_path.exists()

    content = log_path.read_text()
    assert "succeeded" in content
    assert "42.50ms" in content
    assert "Hello world" in content


def test_clean_removes_directory(tmp_path):
    """Should remove entire .grail/ directory."""
    grail_dir = tmp_path / ".grail"
    grail_dir.mkdir()
    (grail_dir / "test.txt").write_text("test")

    mgr = ArtifactsManager(grail_dir)
    mgr.clean()

    assert not grail_dir.exists()


def test_json_artifacts_are_valid(tmp_path):
    """Generated JSON files should be valid JSON."""
    mgr = ArtifactsManager(tmp_path / ".grail")

    externals = {
        "func": ExternalSpec("func", True, [ParameterSpec("x", "int", 10)], "str", "Doc", 1, 0)
    }
    inputs = {"x": InputSpec("x", "int", None, True, 1, 0)}
    check_result = CheckResult("test.pym", True, [], [], {})

    mgr.write_script_artifacts("test", "stubs", "code", check_result, externals, inputs)

    # Should be able to parse JSON
    script_dir = tmp_path / ".grail" / "test"
    check_data = json.loads((script_dir / "check.json").read_text())
    externals_data = json.loads((script_dir / "externals.json").read_text())
    inputs_data = json.loads((script_dir / "inputs.json").read_text())

    assert check_data["valid"] is True
    assert len(externals_data["externals"]) == 1
    assert len(inputs_data["inputs"]) == 1
