"""Test CLI commands."""

import pytest
from pathlib import Path
import tempfile
import os
import json
import subprocess
import sys

from grail.cli import cmd_init, cmd_check, cmd_clean, cmd_run, cmd_watch
import argparse


def test_cmd_init_creates_directory(tmp_path, monkeypatch):
    """Should create .grail/ directory."""
    monkeypatch.chdir(tmp_path)

    args = argparse.Namespace()
    cmd_init(args)

    assert (tmp_path / ".grail").exists()
    assert (tmp_path / "example.pym").exists()


def test_cmd_check_valid_file(tmp_path, monkeypatch):
    """Should check valid .pym file."""
    monkeypatch.chdir(tmp_path)

    # Create a valid .pym file
    pym_file = tmp_path / "test.pym"
    pym_file.write_text("""
from grail import external, Input

x: int = Input("x")

@external
async def double(n: int) -> int:
    ...

result = await double(x)
result
""")

    args = argparse.Namespace(files=["test.pym"], format="text", strict=False)
    result = cmd_check(args)

    assert result == 0


def test_cmd_clean_removes_directory(tmp_path, monkeypatch):
    """Should remove .grail/ directory."""
    monkeypatch.chdir(tmp_path)

    grail_dir = tmp_path / ".grail"
    grail_dir.mkdir()
    (grail_dir / "test.txt").write_text("test")

    args = argparse.Namespace()
    cmd_clean(args)

    assert not grail_dir.exists()


def test_run_parses_input_flag(tmp_path):
    """The --input flag should parse key=value pairs into a dict."""
    pym_file = tmp_path / "analysis.pym"
    pym_file.write_text("result = 1")

    output_file = tmp_path / "inputs.json"
    host_file = tmp_path / "host.py"
    host_file.write_text(
        """
import json
from pathlib import Path


def main(script=None, inputs=None):
    Path(r"{output_path}").write_text(json.dumps(inputs or {{}}))
""".format(output_path=str(output_file))
    )

    args = argparse.Namespace(
        file=str(pym_file),
        host=str(host_file),
        input=["budget=5000", "dept=engineering"],
    )

    result = cmd_run(args)

    assert result == 0
    assert json.loads(output_file.read_text()) == {
        "budget": "5000",
        "dept": "engineering",
    }


def test_run_rejects_invalid_input_format(tmp_path, capsys):
    """An --input value without '=' should produce an error."""
    pym_file = tmp_path / "analysis.pym"
    pym_file.write_text("result = 1")

    args = argparse.Namespace(
        file=str(pym_file),
        host=str(tmp_path / "host.py"),
        input=["invalid_no_equals"],
    )

    result = cmd_run(args)
    captured = capsys.readouterr()

    assert result == 1
    assert "Invalid input format" in captured.err


def test_run_input_flag_appears_in_help():
    """The --input flag should appear in the grail run help text."""
    result = subprocess.run(
        [sys.executable, "-m", "grail", "run", "--help"],
        capture_output=True,
        text=True,
    )

    assert "--input" in result.stdout


def test_check_nonexistent_file_shows_friendly_error(capsys):
    """Running grail check on a missing file should show a clear error."""
    args = argparse.Namespace(files=["missing.pym"], format="text", strict=False, verbose=False)

    result = cmd_check(args)
    captured = capsys.readouterr()

    assert result == 1
    assert "File not found:" in captured.err
    assert "not found" in captured.err.lower()
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_check_invalid_pym_shows_friendly_error(tmp_path, capsys):
    """Running grail check on a malformed .pym should show the parse error clearly."""
    bad_file = tmp_path / "bad.pym"
    bad_file.write_text("def foo(:\n")

    args = argparse.Namespace(
        files=[str(bad_file)],
        format="text",
        strict=False,
        verbose=False,
    )

    result = cmd_check(args)
    captured = capsys.readouterr()

    assert result == 1
    assert "Syntax error" in captured.err
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_watch_missing_dependency_shows_install_hint(capsys, monkeypatch):
    """When watchfiles is not installed, grail watch should suggest pip install grail[watch]."""
    import builtins

    original_import = builtins.__import__

    def mocked_import(name, *args, **kwargs):
        if name == "watchfiles":
            raise ImportError("No module named 'watchfiles'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mocked_import)

    args = argparse.Namespace(dir=None)
    result = cmd_watch(args)
    captured = capsys.readouterr()

    assert result == 1
    assert "pip install grail[watch]" in captured.err
