"""Integration tests verifying artifact contents."""

import ast

import pytest

import grail
from grail.stubs import generate_stubs


@pytest.mark.integration
def test_stubs_artifact_matches_generated_stubs(tmp_path):
    """The stubs.pyi artifact should match what generate_stubs() produces."""
    pym_path = tmp_path / "verify.pym"
    pym_path.write_text(
        """
from grail import external, Input

name: str = Input("name")

@external
async def greet(person: str) -> str:
    ...

await greet(name)
"""
    )

    grail_dir = tmp_path / ".grail"
    script = grail.load(pym_path, grail_dir=grail_dir)

    stubs_path = grail_dir / "verify" / "stubs.pyi"
    stubs_artifact = stubs_path.read_text()
    generated_stubs = generate_stubs(script.externals, script.inputs)

    assert stubs_artifact == generated_stubs


@pytest.mark.integration
def test_monty_code_artifact_is_valid_python(tmp_path):
    """The monty_code.py artifact should be parseable Python."""
    pym_path = tmp_path / "parseable.pym"
    pym_path.write_text(
        """
from grail import Input

value: int = Input("value")

value + 1
"""
    )

    grail_dir = tmp_path / ".grail"
    grail.load(pym_path, grail_dir=grail_dir)

    monty_code_path = grail_dir / "parseable" / "monty_code.py"
    monty_code = monty_code_path.read_text()

    ast.parse(monty_code)
