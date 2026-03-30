from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Type

from structured_agents.grammar.models import StructuredOutputModel


ConstraintStrategy = Literal["ebnf", "structural_tag", "json_schema"]


@dataclass(frozen=True, slots=True)
class DecodingConstraint:
    """How to constrain the model's output to valid tool calls."""

    strategy: ConstraintStrategy | None = None
    allow_parallel_calls: bool = False
    send_tools_to_api: bool = False
    schema_model: Type[StructuredOutputModel] | None = None
