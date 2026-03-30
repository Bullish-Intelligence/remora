"""Shared type definitions for Remora."""

from __future__ import annotations

from enum import StrEnum


class NodeStatus(StrEnum):
    """Valid states for a code node / agent."""

    IDLE = "idle"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    AWAITING_REVIEW = "awaiting_review"
    ERROR = "error"


class NodeType(StrEnum):
    """Types of discovered code elements."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    SECTION = "section"
    TABLE = "table"
    DIRECTORY = "directory"
    VIRTUAL = "virtual"


class ChangeType(StrEnum):
    """Types of content changes."""

    MODIFIED = "modified"
    CREATED = "created"
    DELETED = "deleted"
    OPENED = "opened"


class EventType(StrEnum):
    """Stable event identifiers decoupled from class names."""

    AGENT_START = "agent_start"
    AGENT_COMPLETE = "agent_complete"
    AGENT_ERROR = "agent_error"
    AGENT_MESSAGE = "agent_message"
    NODE_DISCOVERED = "node_discovered"
    NODE_REMOVED = "node_removed"
    NODE_CHANGED = "node_changed"
    CONTENT_CHANGED = "content_changed"
    HUMAN_INPUT_REQUEST = "human_input_request"
    HUMAN_INPUT_RESPONSE = "human_input_response"
    REWRITE_PROPOSAL = "rewrite_proposal"
    REWRITE_ACCEPTED = "rewrite_accepted"
    REWRITE_REJECTED = "rewrite_rejected"
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    TOOL_RESULT = "tool_result"
    REMORA_TOOL_CALL = "remora_tool_call"
    REMORA_TOOL_RESULT = "remora_tool_result"
    TURN_COMPLETE = "turn_complete"
    TURN_DIGESTED = "turn_digested"
    CUSTOM = "custom"
    CURSOR_FOCUS = "cursor_focus"


STATUS_TRANSITIONS: dict[NodeStatus, set[NodeStatus]] = {
    NodeStatus.IDLE: {NodeStatus.RUNNING},
    NodeStatus.RUNNING: {
        NodeStatus.IDLE,
        NodeStatus.ERROR,
        NodeStatus.AWAITING_INPUT,
        NodeStatus.AWAITING_REVIEW,
    },
    NodeStatus.AWAITING_INPUT: {NodeStatus.RUNNING, NodeStatus.ERROR, NodeStatus.IDLE},
    NodeStatus.AWAITING_REVIEW: {NodeStatus.RUNNING, NodeStatus.IDLE},
    NodeStatus.ERROR: {NodeStatus.IDLE, NodeStatus.RUNNING},
}


def validate_status_transition(current: NodeStatus, target: NodeStatus) -> bool:
    """Return True if the transition is allowed."""
    return target in STATUS_TRANSITIONS.get(current, set())


def serialize_enum(value: StrEnum | str) -> str:
    """Serialize StrEnum values to their stable string representation."""
    return value.value if isinstance(value, StrEnum) else str(value)


__all__ = [
    "NodeStatus",
    "NodeType",
    "ChangeType",
    "EventType",
    "STATUS_TRANSITIONS",
    "validate_status_transition",
    "serialize_enum",
]
