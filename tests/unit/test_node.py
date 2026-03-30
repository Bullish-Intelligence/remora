from __future__ import annotations

import pytest
from pydantic import ValidationError

from remora.core.model.node import Node
from tests.factories import make_node


def make_auth_node() -> Node:
    return make_node(
        node_id="src/auth.py::AuthService.validate_token",
        node_type="method",
        name="validate_token",
        full_name="AuthService.validate_token",
        file_path="src/auth.py",
        start_line=10,
        end_line=26,
        start_byte=120,
        end_byte=420,
        text="def validate_token(token: str) -> bool:\n    return True\n",
        source_hash="abc123",
        parent_id="src/auth.py::AuthService",
        status="idle",
        role="code-agent",
    )


def test_node_creation() -> None:
    node = make_auth_node()
    assert node.node_id == "src/auth.py::AuthService.validate_token"
    assert node.node_type == "method"
    assert node.parent_id == "src/auth.py::AuthService"


def test_node_roundtrip() -> None:
    node = make_auth_node()
    row = node.to_row()
    restored = Node.from_row(row)
    assert restored.model_dump() == node.model_dump()


def test_node_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        Node(
            node_id="src/a.py::a",
            node_type="function",
            name="a",
            full_name="a",
            file_path="src/a.py",
            start_line=1,
            end_line=2,
            text="def a():\n    return 1\n",
            source_hash="h-a",
            status="bogus",
        )
