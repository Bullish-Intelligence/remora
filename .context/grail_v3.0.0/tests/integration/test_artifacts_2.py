"""Test artifact generation and management."""

import pytest
import tempfile
from pathlib import Path
import json

import grail


@pytest.mark.integration
def test_artifacts_created():
    """Test that artifacts are created correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create .pym file
        pym_file = tmpdir / "test.pym"
        pym_file.write_text("""
from grail import external, Input

x: int = Input("x")

@external
async def process(n: int) -> int:
    ...

await process(x)
""")

        # Load with artifacts enabled
        script = grail.load(pym_file, grail_dir=tmpdir / ".grail")

        # Check artifacts exist
        artifacts_dir = tmpdir / ".grail" / "test"
        assert artifacts_dir.exists()
        assert (artifacts_dir / "stubs.pyi").exists()
        assert (artifacts_dir / "monty_code.py").exists()
        assert (artifacts_dir / "check.json").exists()
        assert (artifacts_dir / "externals.json").exists()
        assert (artifacts_dir / "inputs.json").exists()

        # Verify JSON artifacts are valid
        check_data = json.loads((artifacts_dir / "check.json").read_text())
        assert "valid" in check_data

        externals_data = json.loads((artifacts_dir / "externals.json").read_text())
        assert "externals" in externals_data

        inputs_data = json.loads((artifacts_dir / "inputs.json").read_text())
        assert "inputs" in inputs_data
