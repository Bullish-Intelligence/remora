from __future__ import annotations

import json
from typing import Any

from structured_agents.grammar.config import DecodingConstraint
from structured_agents.grammar.models import StructuredOutputModel
from structured_agents.types import ToolSchema


class ConstraintPipeline:
    """Transforms tool schemas plus decoding configuration into vLLM constraints."""

    def __init__(self, config: DecodingConstraint):
        self._config = config

    def constrain(self, tools: list[ToolSchema]) -> dict[str, Any] | None:
        """Return the extra-body payload or None when no constraint is configured."""
        if not tools:
            return None
        strategy = self._config.strategy
        if strategy == "json_schema":
            return build_json_schema_constraint(self._config)
        if strategy == "structural_tag":
            return build_structural_tag_constraint(tools, self._config)
        return None


def build_structural_tag_constraint(
    tools: list[ToolSchema], config: DecodingConstraint
) -> dict[str, Any] | None:
    """Build the `structural_tag` payload that vLLM expects."""
    if config.strategy != "structural_tag":
        return None

    if not tools:
        return None

    structures: list[dict[str, Any]] = []
    triggers: set[str] = set()

    for tool in tools:
        begin_tag = f"<function={tool.name}>"
        trigger = "<function="
        triggers.add(trigger)

        args_schema: dict[str, Any] = tool.parameters

        structures.append(
            {
                "begin": begin_tag,
                "schema": args_schema,
                "end": "</function>",
            }
        )

    legacy_payload = {
        "type": "structural_tag",
        "structures": structures,
        "triggers": sorted(triggers),
    }

    return {"structured_outputs": {"structural_tag": json.dumps(legacy_payload)}}


def build_json_schema_constraint(config: DecodingConstraint) -> dict[str, Any] | None:
    """Build a `json` structured output payload backed by a Pydantic model."""
    if config.strategy != "json_schema":
        return None

    schema_model = config.schema_model
    if schema_model is None:
        raise ValueError("JSON schema strategy requires a StructuredOutputModel")

    if not issubclass(schema_model, StructuredOutputModel):
        raise TypeError("schema_model must inherit from StructuredOutputModel")

    schema = schema_model.model_json_schema()
    _validate_json_schema(schema)

    return {"structured_outputs": {"json": schema}}


def _validate_json_schema(schema: dict[str, Any]) -> None:
    if _contains_unsupported_type(schema, "qwen_xml_parameter"):
        raise ValueError(
            "qwen_xml_parameter schemas are unsupported by xgrammar/vLLM JSON schema"
        )


def _contains_unsupported_type(data: Any, target: str) -> bool:
    if isinstance(data, dict):
        if data.get("type") == target:
            return True
        return any(_contains_unsupported_type(value, target) for value in data.values())
    if isinstance(data, list):
        return any(_contains_unsupported_type(item, target) for item in data)
    return False
