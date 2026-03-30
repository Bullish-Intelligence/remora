"""Models package - backwards compatibility shim.

The models package is deprecated. Use the parsing package instead:
- ResponseParser, DefaultResponseParser -> from structured_agents.parsing
- get_response_parser -> from structured_agents.parsing

ModelAdapter has been removed - AgentKernel now takes response_parser
and constraint_pipeline directly.
"""

from structured_agents.parsing import (
    ResponseParser,
    DefaultResponseParser,
    get_response_parser,
)

# Backwards compatibility alias
QwenResponseParser = DefaultResponseParser

__all__ = [
    "ResponseParser",
    "DefaultResponseParser",
    "QwenResponseParser",
    "get_response_parser",
]
