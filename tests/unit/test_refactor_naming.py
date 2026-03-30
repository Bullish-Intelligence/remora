from __future__ import annotations

import pytest
from pydantic import ValidationError

from remora.core.model.config import Config, InfraConfig
from remora.core.model.node import Node


def test_new_core_symbols_exist() -> None:
    assert Node is not None


def test_node_uses_role_field() -> None:
    node = Node(
        node_id="src/app.py::alpha",
        node_type="function",
        name="alpha",
        full_name="alpha",
        file_path="src/app.py",
        start_line=1,
        end_line=2,
        text="def alpha():\n    return 1\n",
        source_hash="hash-a",
        role="code-agent",
    )
    assert node.role == "code-agent"


def test_config_workspace_root_works() -> None:
    config = Config(infra=InfraConfig(workspace_root=".remora-workspace"))
    assert config.infra.workspace_root == ".remora-workspace"


def test_legacy_swarm_root_key_rejected() -> None:
    """Old 'swarm_root' key is no longer silently migrated."""
    with pytest.raises(ValidationError):
        Config(swarm_root=".remora-legacy")
