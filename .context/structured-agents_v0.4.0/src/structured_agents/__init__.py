"""structured-agents - Structured tool orchestration with grammar-constrained LLM outputs."""

from structured_agents.types import (
    Message,
    ToolCall,
    ToolResult,
    ToolSchema,
    TokenUsage,
    StepResult,
    RunResult,
)
from structured_agents.tools import Tool
from structured_agents.parsing import (
    ResponseParser,
    DefaultResponseParser,
    get_response_parser,
)
from structured_agents.grammar import (
    DecodingConstraint,
    StructuredOutputModel,
    ConstraintPipeline,
)
from structured_agents.events import (
    Observer,
    NullObserver,
    CompositeObserver,
    Event,
    KernelEvent,
    KernelStartEvent,
    KernelEndEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from structured_agents.kernel import AgentKernel
from structured_agents.client import (
    LLMClient,
    CompletionResponse,
    OpenAICompatibleClient,
    LiteLLMClient,
    build_client,
)
from structured_agents.exceptions import (
    StructuredAgentsError,
    KernelError,
    ToolExecutionError,
)

__version__ = "0.4.0"

__all__ = [
    # Types
    "Message",
    "ToolCall",
    "ToolResult",
    "ToolSchema",
    "TokenUsage",
    "StepResult",
    "RunResult",
    # Tools
    "Tool",
    # Parsing
    "ResponseParser",
    "DefaultResponseParser",
    "get_response_parser",
    # Grammar
    "DecodingConstraint",
    "StructuredOutputModel",
    "ConstraintPipeline",
    # Events
    "Observer",
    "NullObserver",
    "CompositeObserver",
    "Event",
    "KernelEvent",
    "KernelStartEvent",
    "KernelEndEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "TurnCompleteEvent",
    # Core
    "AgentKernel",
    # Client
    "LLMClient",
    "CompletionResponse",
    "OpenAICompatibleClient",
    "LiteLLMClient",
    "build_client",
    # Exceptions
    "StructuredAgentsError",
    "KernelError",
    "ToolExecutionError",
]
