from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import grail
import pytest
from structured_agents.types import ToolCall

import remora.core.tools.grail as grail_module
from remora.core.tools.grail import (
    GrailTool,
    _build_parameters,
    _load_script_from_source,
    discover_tools,
)

SCRIPT_SOURCE = """
from grail import Input, external

name: str = Input("name")
count: int = Input("count", default=1)

@external
async def echo(text: str) -> str: ...

result = await echo(name)
return {"value": result, "count": count}
""".strip()


def _load_script(tmp_path: Path, filename: str = "demo.pym") -> grail.GrailScript:
    path = tmp_path / filename
    path.write_text(SCRIPT_SOURCE, encoding="utf-8")
    return grail.load(path)


class _WorkspaceStub:
    def __init__(self, files: dict[str, str], *, missing_tools_dir: bool = False):
        self._files = files
        self._missing_tools_dir = missing_tools_dir

    async def list_dir(self, path: str = ".") -> list[str]:
        if self._missing_tools_dir:
            raise FileNotFoundError(path)
        prefix = f"{path.rstrip('/')}/"
        names = []
        for full_path in self._files:
            if full_path.startswith(prefix):
                suffix = full_path[len(prefix) :]
                if "/" not in suffix:
                    names.append(suffix)
        return sorted(names)

    async def read(self, path: str) -> str:
        return self._files[path]


def test_build_parameters(tmp_path: Path) -> None:
    script = _load_script(tmp_path)
    schema = _build_parameters(script)
    assert schema["type"] == "object"
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["count"]["type"] == "integer"
    assert schema["required"] == ["name"]


def test_grail_tool_schema(tmp_path: Path) -> None:
    script = _load_script(tmp_path)
    tool = GrailTool(script=script, capabilities={"echo": lambda _: "ok"})
    assert tool.schema.name == "demo"
    assert tool.schema.parameters["properties"]["name"]["type"] == "string"


def test_grail_tool_description_from_source_comment(tmp_path: Path) -> None:
    script = _load_script(tmp_path)
    source = (
        "# Send a message to another agent.\n"
        "from grail import Input\n"
        'name: str = Input("name")\n'
        "result = name\n"
    )
    tool = GrailTool(script=script, source=source)
    assert tool.schema.description == "Send a message to another agent."


@pytest.mark.asyncio
async def test_grail_tool_execute(tmp_path: Path) -> None:
    _ = _load_script(tmp_path)

    class ScriptStub:
        name = "demo"
        inputs = {}
        externals = {"echo": object()}

        async def run(self, inputs, externals):  # noqa: ANN001, ANN201
            echoed = await externals["echo"](inputs["name"])
            return {"value": echoed, "count": inputs["count"]}

    async def echo(text: str) -> str:
        return f"echo:{text}"

    tool = GrailTool(script=ScriptStub(), capabilities={"echo": echo, "unused": echo})
    result = await tool.execute(
        {"name": "remora", "count": 2},
        ToolCall(id="call-1", name="demo", arguments={"name": "remora"}),
    )

    payload = json.loads(result.output)
    assert result.is_error is False
    assert result.call_id == "call-1"
    assert payload == {"value": "echo:remora", "count": 2}


@pytest.mark.asyncio
async def test_grail_tool_error_handling(tmp_path: Path) -> None:
    _ = _load_script(tmp_path)

    class ScriptStub:
        name = "demo"
        inputs = {}
        externals = {"echo": object()}

        async def run(self, inputs, externals):  # noqa: ANN001, ANN201
            return await externals["echo"](inputs["name"])

    async def fail(_: str) -> str:
        raise RuntimeError("boom")

    tool = GrailTool(script=ScriptStub(), capabilities={"echo": fail})
    result = await tool.execute({"name": "x"}, ToolCall(id="call-2", name="demo", arguments={}))
    assert result.is_error is True
    assert "boom" in result.output


@pytest.mark.asyncio
async def test_grail_tool_execute_applies_optional_defaults(tmp_path: Path) -> None:
    _ = _load_script(tmp_path)

    class ScriptStub:
        name = "demo"
        inputs = {
            "name": SimpleNamespace(required=True, default=None, type_annotation="str"),
            "count": SimpleNamespace(required=False, default=7, type_annotation="int"),
        }
        externals = {}

        async def run(self, inputs, externals):  # noqa: ANN001, ANN201
            del externals
            return {"name": inputs["name"], "count": inputs["count"]}

    tool = GrailTool(script=ScriptStub(), capabilities={})
    result = await tool.execute(
        {"name": "remora"},
        ToolCall(id="call-defaults", name="demo", arguments={"name": "remora"}),
    )

    payload = json.loads(result.output)
    assert result.is_error is False
    assert payload == {"name": "remora", "count": 7}


@pytest.mark.asyncio
async def test_discover_tools_from_workspace() -> None:
    workspace = _WorkspaceStub(
        {
            "_bundle/tools/demo.pym": SCRIPT_SOURCE,
            "_bundle/tools/ignore.txt": "x",
        }
    )

    async def echo(text: str) -> str:
        return text

    tools = await discover_tools(workspace, capabilities={"echo": echo})
    assert len(tools) == 1
    assert tools[0].schema.name == "demo"


@pytest.mark.asyncio
async def test_discover_tools_empty() -> None:
    workspace = _WorkspaceStub({}, missing_tools_dir=True)
    tools = await discover_tools(workspace, capabilities={})
    assert tools == []


def test_load_script_from_source_uses_cache() -> None:
    first = _load_script_from_source(SCRIPT_SOURCE, "demo")
    second = _load_script_from_source(SCRIPT_SOURCE, "demo")
    assert first is second


def test_script_source_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    grail_module._PARSED_SCRIPT_CACHE.clear()
    monkeypatch.setattr(grail_module, "_MAX_SCRIPT_CACHE", 2)

    source_one = SCRIPT_SOURCE + "\n# one"
    _load_script_from_source(source_one, "demo_one")
    _load_script_from_source(SCRIPT_SOURCE + "\n# two", "demo_two")
    _load_script_from_source(SCRIPT_SOURCE + "\n# three", "demo_three")

    assert len(grail_module._PARSED_SCRIPT_CACHE) == 2
    source_one_hash = hashlib.sha256(source_one.encode("utf-8")).hexdigest()[:16]
    assert source_one_hash not in grail_module._PARSED_SCRIPT_CACHE

    grail_module._PARSED_SCRIPT_CACHE.clear()


@pytest.mark.asyncio
async def test_discover_tools_logs_load_failure(caplog) -> None:
    workspace = _WorkspaceStub({"_bundle/tools/bad.pym": "def broken(:\n"})

    with caplog.at_level(logging.DEBUG, logger="remora.core.tools.grail"):
        tools = await discover_tools(workspace, capabilities={})

    assert tools == []
    messages = [record.getMessage() for record in caplog.records]
    assert any("Failed to load tool bad.pym" in message for message in messages)
    assert any("Loaded 0 Grail tool(s)" in message for message in messages)


@pytest.mark.asyncio
async def test_grail_tool_execute_logs_start_and_failure(tmp_path: Path, caplog) -> None:
    _ = _load_script(tmp_path)

    class ScriptStub:
        name = "demo"
        inputs = {}
        externals = {"echo": object()}

        async def run(self, inputs, externals):  # noqa: ANN001, ANN201
            return await externals["echo"](inputs["name"])

    async def fail(_: str) -> str:
        raise RuntimeError("boom")

    tool = GrailTool(script=ScriptStub(), capabilities={"echo": fail}, agent_id="node-x")
    with caplog.at_level(logging.DEBUG, logger="remora.core.tools.grail"):
        result = await tool.execute({"name": "x"}, ToolCall(id="call-3", name="demo", arguments={}))

    assert result.is_error is True
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Tool start agent=node-x tool=demo call_id=call-3" in message for message in messages
    )
    assert any(
        "Tool failed agent=node-x tool=demo call_id=call-3" in message for message in messages
    )


@pytest.mark.asyncio
async def test_grail_tool_execute_logs_full_output_not_truncated(caplog) -> None:
    long_output = "x" * 1200 + "TAIL"

    class ScriptStub:
        name = "demo"
        inputs = {}
        externals = {}

        async def run(self, inputs, externals):  # noqa: ANN001, ANN201
            del inputs, externals
            return long_output

    tool = GrailTool(script=ScriptStub(), capabilities={}, agent_id="node-x")
    with caplog.at_level(logging.DEBUG, logger="remora.core.tools.grail"):
        result = await tool.execute({}, ToolCall(id="call-9", name="demo", arguments={}))

    assert result.is_error is False
    messages = [record.getMessage() for record in caplog.records]
    completion = next(
        message
        for message in messages
        if "Tool complete agent=node-x tool=demo call_id=call-9" in message
    )
    assert "TAIL" in completion
    assert "..." not in completion


@pytest.mark.asyncio
async def test_grail_tool_logging_preserves_newlines_in_output(caplog) -> None:
    class ScriptStub:
        name = "demo"
        inputs = {}
        externals = {}

        async def run(self, inputs, externals):  # noqa: ANN001, ANN201
            del inputs, externals
            return "line1\nline2"

    tool = GrailTool(script=ScriptStub(), capabilities={}, agent_id="node-x")
    with caplog.at_level(logging.DEBUG, logger="remora.core.tools.grail"):
        await tool.execute({}, ToolCall(id="call-10", name="demo", arguments={}))

    completion = next(
        message
        for message in (record.getMessage() for record in caplog.records)
        if "Tool complete agent=node-x tool=demo call_id=call-10" in message
    )
    assert "line1\nline2" in completion
    assert "line1\\nline2" not in completion


def test_review_diff_script_parses() -> None:
    script = grail.load(Path("src/remora/defaults/bundles/review-agent/tools/review_diff.pym"))
    assert script.name == "review_diff"


def test_submit_review_script_parses() -> None:
    script = grail.load(Path("src/remora/defaults/bundles/review-agent/tools/submit_review.pym"))
    assert script.name == "submit_review"


def test_suggest_tests_script_parses() -> None:
    script = grail.load(Path("src/remora/defaults/bundles/test-agent/tools/suggest_tests.pym"))
    assert script.name == "suggest_tests"


def test_ask_human_script_parses() -> None:
    script = grail.load(Path("src/remora/defaults/bundles/system/tools/ask_human.pym"))
    assert script.name == "ask_human"
