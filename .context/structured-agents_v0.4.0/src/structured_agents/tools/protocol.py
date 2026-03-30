"""Tool protocol definition."""

from __future__ import annotations
from typing import Protocol, Any
from structured_agents.types import ToolCall, ToolSchema, ToolResult


class Tool(Protocol):
    """A tool has a schema and can execute with arguments."""

    @property
    def schema(self) -> ToolSchema: ...

    async def execute(
        self, arguments: dict[str, Any], context: ToolCall | None
    ) -> ToolResult: ...
