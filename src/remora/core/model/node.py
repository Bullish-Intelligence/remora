"""Canonical node model."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from remora.core.model.types import NodeStatus, NodeType, serialize_enum


class Node(BaseModel):
    """Unified node model joining discovered element data with agent state."""

    model_config = ConfigDict(frozen=False)

    node_id: str
    node_type: NodeType
    name: str
    full_name: str
    file_path: str
    start_line: int
    end_line: int
    start_byte: int = 0
    end_byte: int = 0
    text: str
    source_hash: str
    parent_id: str | None = None
    status: NodeStatus = NodeStatus.IDLE
    role: str | None = None

    def to_row(self) -> dict[str, Any]:
        """Serialize the model into a sqlite-ready row."""
        data = self.model_dump()
        data["node_type"] = serialize_enum(data["node_type"])
        data["status"] = serialize_enum(data["status"])
        return data

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Node:
        """Hydrate a model from a sqlite row representation."""
        data = dict(row)
        return cls(**data)


__all__ = ["Node"]
