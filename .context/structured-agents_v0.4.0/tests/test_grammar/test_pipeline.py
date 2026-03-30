from __future__ import annotations

import pytest

from structured_agents.grammar import DecodingConstraint, StructuredOutputModel
from structured_agents.grammar.pipeline import (
    ConstraintPipeline,
    build_json_schema_constraint,
    build_structural_tag_constraint,
)
from structured_agents.types import ToolSchema


class SampleOutput(StructuredOutputModel):
    value: int
    note: str


class BadStructuredOutput(StructuredOutputModel):
    @classmethod
    def model_json_schema(cls, *args: object, **kwargs: object) -> dict[str, object]:
        return {"type": "qwen_xml_parameter"}


def test_decoding_constraint_defaults() -> None:
    constraint = DecodingConstraint()
    assert constraint.strategy is None
    assert not constraint.allow_parallel_calls
    assert not constraint.send_tools_to_api
    assert constraint.schema_model is None


def test_constraint_pipeline_requires_strategy() -> None:
    pipeline = ConstraintPipeline(DecodingConstraint())
    assert (
        pipeline.constrain(
            [ToolSchema(name="add", description="Add", parameters={"type": "object"})]
        )
        is None
    )


def test_constraint_pipeline_json_schema() -> None:
    constraint = DecodingConstraint(strategy="json_schema", schema_model=SampleOutput)
    pipeline = ConstraintPipeline(constraint)
    tools = [
        ToolSchema(
            name="log",
            description="Log tool",
            parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
        )
    ]

    payload = pipeline.constrain(tools)
    assert payload is not None
    structured = payload["structured_outputs"]
    assert "json" in structured
    schema = structured["json"]
    assert schema["title"].lower().startswith("sampleoutput")


def test_json_schema_validation_rejects_qwen_xml() -> None:
    constraint = DecodingConstraint(
        strategy="json_schema", schema_model=BadStructuredOutput
    )
    with pytest.raises(ValueError):
        build_json_schema_constraint(constraint)


def test_constraint_pipeline_structural_tag() -> None:
    constraint = DecodingConstraint(
        strategy="structural_tag", allow_parallel_calls=True
    )
    tools = [
        ToolSchema(
            name="echo",
            description="Echo",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )
    ]

    payload = build_structural_tag_constraint(tools, constraint)
    assert payload is not None
    structured = payload["structured_outputs"]
    assert "structural_tag" in structured
