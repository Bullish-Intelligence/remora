"""Tests for public API surface."""


def test_all_exports_importable() -> None:
    """Verify all __all__ exports are importable."""
    import structured_agents

    for name in structured_agents.__all__:
        obj = getattr(structured_agents, name)
        assert obj is not None, f"Export {name} is None"


def test_version_exists() -> None:
    import structured_agents

    assert hasattr(structured_agents, "__version__")
    assert isinstance(structured_agents.__version__, str)
    assert structured_agents.__version__ == "0.4.0"


def test_core_classes_importable() -> None:
    from structured_agents import (
        AgentKernel,
        DefaultResponseParser,
        ResponseParser,
        get_response_parser,
        Message,
        ToolCall,
        ToolResult,
        ToolSchema,
        TokenUsage,
        StepResult,
        RunResult,
        build_client,
        LLMClient,
        OpenAICompatibleClient,
        LiteLLMClient,
    )

    assert AgentKernel.__name__ == "AgentKernel"
    assert DefaultResponseParser.__name__ == "DefaultResponseParser"
    assert Message.__name__ == "Message"
    assert ToolCall.__name__ == "ToolCall"
    assert ToolResult.__name__ == "ToolResult"
    assert ToolSchema.__name__ == "ToolSchema"
    assert TokenUsage.__name__ == "TokenUsage"
    assert StepResult.__name__ == "StepResult"
    assert RunResult.__name__ == "RunResult"
    assert build_client.__name__ == "build_client"
    assert LLMClient.__name__ == "LLMClient"
    assert OpenAICompatibleClient.__name__ == "OpenAICompatibleClient"
    assert LiteLLMClient.__name__ == "LiteLLMClient"


def test_events_importable() -> None:
    from structured_agents import (
        Event,
        KernelEvent,
        KernelStartEvent,
        KernelEndEvent,
        ModelRequestEvent,
        ModelResponseEvent,
        ToolCallEvent,
        ToolResultEvent,
        TurnCompleteEvent,
        Observer,
        NullObserver,
        CompositeObserver,
    )

    assert KernelEvent.__name__ == "KernelEvent"
    assert KernelStartEvent.__name__ == "KernelStartEvent"


def test_grammar_importable() -> None:
    from structured_agents import (
        DecodingConstraint,
        StructuredOutputModel,
        ConstraintPipeline,
    )

    assert DecodingConstraint.__name__ == "DecodingConstraint"
    assert StructuredOutputModel.__name__ == "StructuredOutputModel"
    assert ConstraintPipeline.__name__ == "ConstraintPipeline"


def test_backwards_compat_models_package() -> None:
    """Test that old imports from models package still work."""
    from structured_agents.models import (
        ResponseParser,
        DefaultResponseParser,
        QwenResponseParser,
        get_response_parser,
    )

    # QwenResponseParser should be an alias for DefaultResponseParser
    assert QwenResponseParser is DefaultResponseParser
