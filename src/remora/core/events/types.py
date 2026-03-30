"""Event types and base classes."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from remora.core.model.types import ChangeType, EventType


class Event(BaseModel):
    """Base event envelope."""

    event_type: str = ""
    timestamp: float = Field(default_factory=time.time)
    event_id: int | None = None
    correlation_id: str | None = None
    tags: tuple[str, ...] = ()

    def summary(self) -> str:
        """Return a human-readable summary of this event."""
        return ""

    def to_envelope(self) -> dict[str, Any]:
        payload = self.model_dump(
            exclude={"event_type", "timestamp", "event_id", "correlation_id", "tags"},
        )
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "tags": list(self.tags),
            "payload": payload,
        }


class AgentStartEvent(Event):
    event_type: str = EventType.AGENT_START
    agent_id: str
    node_name: str = ""


class AgentCompleteEvent(Event):
    event_type: str = EventType.AGENT_COMPLETE
    agent_id: str
    result_summary: str = ""
    full_response: str = ""
    user_message: str = ""

    def summary(self) -> str:
        return self.result_summary


class AgentErrorEvent(Event):
    event_type: str = EventType.AGENT_ERROR
    agent_id: str
    error: str
    error_class: str = ""
    error_reason: str = ""

    def summary(self) -> str:
        return self.error


class AgentMessageEvent(Event):
    event_type: str = EventType.AGENT_MESSAGE
    from_agent: str
    to_agent: str
    content: str

    def summary(self) -> str:
        return self.content


class NodeDiscoveredEvent(Event):
    event_type: str = EventType.NODE_DISCOVERED
    node_id: str
    node_type: str
    file_path: str
    name: str


class NodeRemovedEvent(Event):
    event_type: str = EventType.NODE_REMOVED
    node_id: str
    node_type: str
    file_path: str
    name: str


class NodeChangedEvent(Event):
    event_type: str = EventType.NODE_CHANGED
    node_id: str
    old_hash: str
    new_hash: str
    file_path: str | None = None


class ContentChangedEvent(Event):
    event_type: str = EventType.CONTENT_CHANGED
    path: str
    change_type: ChangeType = ChangeType.MODIFIED
    agent_id: str | None = None
    old_hash: str | None = None
    new_hash: str | None = None


class HumanInputRequestEvent(Event):
    """Agent asks the human for input and waits for a response."""

    event_type: str = EventType.HUMAN_INPUT_REQUEST
    agent_id: str
    request_id: str
    question: str
    options: tuple[str, ...] = ()


class HumanInputResponseEvent(Event):
    """Human answered an agent's pending input request."""

    event_type: str = EventType.HUMAN_INPUT_RESPONSE
    agent_id: str
    request_id: str
    response: str


class RewriteProposalEvent(Event):
    """Agent indicates workspace changes are ready for human review."""

    event_type: str = EventType.REWRITE_PROPOSAL
    agent_id: str
    proposal_id: str
    files: tuple[str, ...] = ()
    reason: str = ""


class RewriteAcceptedEvent(Event):
    """Human accepted an agent rewrite proposal."""

    event_type: str = EventType.REWRITE_ACCEPTED
    agent_id: str
    proposal_id: str


class RewriteRejectedEvent(Event):
    """Human rejected an agent rewrite proposal."""

    event_type: str = EventType.REWRITE_REJECTED
    agent_id: str
    proposal_id: str
    feedback: str = ""


class ModelRequestEvent(Event):
    """LLM request started for an agent turn."""

    event_type: str = EventType.MODEL_REQUEST
    agent_id: str
    model: str = ""
    tool_count: int = 0
    turn: int = 0


class ModelResponseEvent(Event):
    """LLM response received for an agent turn."""

    event_type: str = EventType.MODEL_RESPONSE
    agent_id: str
    response_preview: str = ""
    duration_ms: int = 0
    tool_calls_count: int = 0
    turn: int = 0


class RemoraToolCallEvent(Event):
    """Agent is about to call a tool."""

    event_type: str = EventType.REMORA_TOOL_CALL
    agent_id: str
    tool_name: str
    arguments_summary: str = ""
    turn: int = 0


class RemoraToolResultEvent(Event):
    """Tool execution completed within a turn."""

    event_type: str = EventType.REMORA_TOOL_RESULT
    agent_id: str
    tool_name: str
    is_error: bool = False
    error_class: str = ""
    error_reason: str = ""
    duration_ms: int = 0
    output_preview: str = ""
    turn: int = 0


class TurnCompleteEvent(Event):
    """One model/tool turn cycle completed."""

    event_type: str = EventType.TURN_COMPLETE
    agent_id: str
    turn: int = 0
    tool_calls_count: int = 0
    errors_count: int = 0
    error_summary: str = ""


class TurnDigestedEvent(Event):
    """Emitted after Layer 1 reflection completes for an agent turn."""

    event_type: str = EventType.TURN_DIGESTED
    agent_id: str
    digest_summary: str = ""
    has_reflection: bool = False
    has_links: bool = False

    def summary(self) -> str:
        return self.digest_summary


class CustomEvent(Event):
    event_type: str = EventType.CUSTOM
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_envelope(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "tags": list(self.tags),
            "payload": self.payload,
        }


class ToolResultEvent(Event):
    event_type: str = EventType.TOOL_RESULT
    agent_id: str
    tool_name: str
    result_summary: str = ""

    def summary(self) -> str:
        return self.result_summary


class CursorFocusEvent(Event):
    """Emitted when the editor cursor focuses on a code element."""

    event_type: str = EventType.CURSOR_FOCUS
    file_path: str
    line: int
    character: int
    node_id: str | None = None
    node_name: str | None = None
    node_type: str | None = None


EventHandler = Callable[[Event], Any]


__all__ = [
    "Event",
    "AgentStartEvent",
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "AgentMessageEvent",
    "NodeDiscoveredEvent",
    "NodeRemovedEvent",
    "NodeChangedEvent",
    "ContentChangedEvent",
    "HumanInputRequestEvent",
    "HumanInputResponseEvent",
    "RewriteProposalEvent",
    "RewriteAcceptedEvent",
    "RewriteRejectedEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    "RemoraToolCallEvent",
    "RemoraToolResultEvent",
    "TurnCompleteEvent",
    "TurnDigestedEvent",
    "CustomEvent",
    "ToolResultEvent",
    "CursorFocusEvent",
    "EventHandler",
]
