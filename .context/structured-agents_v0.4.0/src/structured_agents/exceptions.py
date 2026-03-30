"""Exception hierarchy for structured-agents."""

from __future__ import annotations


class StructuredAgentsError(Exception):
    """Base exception for all structured-agents errors."""


class KernelError(StructuredAgentsError):
    """Error during kernel execution."""

    def __init__(
        self, message: str, turn: int | None = None, phase: str | None = None
    ) -> None:
        super().__init__(message)
        self.turn = turn
        self.phase = phase


class ToolExecutionError(StructuredAgentsError):
    """Error during tool execution."""

    def __init__(
        self,
        message: str,
        tool_name: str,
        call_id: str,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.tool_name = tool_name
        self.call_id = call_id
        self.code = code
