from __future__ import annotations

from structured_agents import AgentKernel, Message

from remora.core.agents.kernel import create_kernel, extract_response_text


def test_create_kernel() -> None:
    kernel = create_kernel(
        model_name="gpt-4o-mini",
        base_url="http://localhost:8000/v1",
        api_key="",
        tools=[],
        client=object(),
    )
    assert isinstance(kernel, AgentKernel)


def test_extract_response_text() -> None:
    class _Result:
        def __init__(self) -> None:
            self.final_message = Message(role="assistant", content="hello")

    assert extract_response_text(_Result()) == "hello"
    assert extract_response_text({"x": 1}) == "{'x': 1}"
