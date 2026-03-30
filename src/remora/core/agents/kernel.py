"""Thin wrapper around structured_agents for kernel creation."""

from __future__ import annotations

from typing import Any

from structured_agents import (
    AgentKernel,
    ConstraintPipeline,
    NullObserver,
    build_client,
    get_response_parser,
)

from remora.core.model.errors import ModelError


def create_kernel(
    *,
    model_name: str,
    base_url: str,
    api_key: str,
    timeout: float = 300.0,
    tools: list[Any] | None = None,
    observer: Any | None = None,
    grammar_config: Any | None = None,
    client: Any | None = None,
) -> AgentKernel:
    """Create an AgentKernel with Remora defaults."""
    if client is None:
        client = build_client(
            {
                "base_url": base_url,
                "api_key": api_key or "EMPTY",
                "model": model_name,
                "timeout": timeout,
            }
        )

    response_parser = get_response_parser(model_name)
    constraint_pipeline = ConstraintPipeline(grammar_config) if grammar_config else None

    return AgentKernel(
        client=client,
        response_parser=response_parser,
        tools=tools or [],
        observer=observer or NullObserver(),
        constraint_pipeline=constraint_pipeline,
    )


async def run_kernel(kernel: AgentKernel, *args: Any, **kwargs: Any) -> Any:
    """Run the kernel with ModelError wrapping at the boundary."""
    try:
        return await kernel.run(*args, **kwargs)
    except Exception as exc:
        raise ModelError(f"Model call failed: {exc}") from exc


def extract_response_text(result: Any) -> str:
    """Extract the final text content from a kernel run result."""
    if hasattr(result, "final_message"):
        final_message = result.final_message
        if hasattr(final_message, "content") and final_message.content:
            return final_message.content
    return str(result)


__all__ = ["create_kernel", "extract_response_text", "run_kernel"]
