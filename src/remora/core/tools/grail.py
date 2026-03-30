"""Grail tool loading and execution helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Any

import grail
from fsdantic import FileNotFoundError as FsdFileNotFoundError
from grail.errors import GrailError
from structured_agents.types import ToolCall, ToolResult, ToolSchema

from remora.core.model.errors import ToolError
from remora.core.storage.workspace import AgentWorkspace

logger = logging.getLogger(__name__)

_TYPE_MAP = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
}
_MAX_SCRIPT_CACHE = 256
_PARSED_SCRIPT_CACHE: dict[str, grail.GrailScript] = {}


def _build_parameters(script: grail.GrailScript) -> dict[str, Any]:
    """Build JSON Schema parameters from Grail input declarations."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, spec in script.inputs.items():
        schema_type = _TYPE_MAP.get(spec.type_annotation, "string")
        properties[name] = {"type": schema_type}
        if spec.required:
            required.append(name)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _load_script_from_source(source: str, name: str) -> grail.GrailScript:
    content_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    cached = _PARSED_SCRIPT_CACHE.get(content_hash)
    if cached is not None:
        return cached

    filename = f"{name}.pym" if not name.endswith(".pym") else name
    with tempfile.TemporaryDirectory(prefix="remora-grail-") as temp_dir:
        script_path = Path(temp_dir) / filename
        script_path.write_text(source, encoding="utf-8")
        try:
            script = grail.load(script_path)
        except GrailError as exc:
            raise ToolError(f"Failed to load tool script '{filename}': {exc}") from exc

    if len(_PARSED_SCRIPT_CACHE) >= _MAX_SCRIPT_CACHE:
        _PARSED_SCRIPT_CACHE.pop(next(iter(_PARSED_SCRIPT_CACHE)))
    _PARSED_SCRIPT_CACHE[content_hash] = script
    return script


def _extract_description(script: grail.GrailScript, source: str | None = None) -> str:
    """Extract a tool description from script metadata or source text."""
    docstring = getattr(script, "docstring", None)
    if isinstance(docstring, str) and docstring.strip():
        return docstring.strip()

    if source:
        lines = source.strip().splitlines()
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#") and not stripped.startswith("#!"):
                return stripped.lstrip("# ").strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                quote = stripped[:3]
                if stripped.count(quote) >= 2:
                    inner = stripped[3 : stripped.index(quote, 3)].strip()
                    if inner:
                        return inner
                break
            if stripped.startswith("from ") or stripped.startswith("import "):
                continue
            break

    return f"Tool: {script.name}"


class GrailTool:
    """A structured-agents tool wrapper around a GrailScript."""

    def __init__(
        self,
        script: grail.GrailScript,
        *,
        capabilities: dict[str, Any] | None = None,
        name_override: str | None = None,
        agent_id: str = "?",
        source_file: str | None = None,
        source: str | None = None,
    ):
        self._script = script
        self._capabilities = capabilities if capabilities is not None else {}
        self._agent_id = agent_id
        self._source_file = source_file or f"{script.name}.pym"
        self._schema = ToolSchema(
            name=name_override or script.name,
            description=_extract_description(script, source),
            parameters=_build_parameters(script),
        )

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        call_id = context.id if context else ""
        normalized_arguments = self._normalize_arguments(arguments)
        started = time.perf_counter()
        logger.debug(
            "Tool start agent=%s tool=%s call_id=%s source=%s args=%s",
            self._agent_id,
            self._schema.name,
            call_id or "-",
            self._source_file,
            normalized_arguments,
        )
        try:
            try:
                used_capabilities = {
                    name: fn
                    for name, fn in self._capabilities.items()
                    if name in self._script.externals
                }
                result = await self._script.run(
                    inputs=normalized_arguments,
                    externals=used_capabilities,
                )
                output = result if isinstance(result, str) else json.dumps(result)
                logger.debug(
                    "Tool complete agent=%s tool=%s call_id=%s duration_ms=%.1f output=%s",
                    self._agent_id,
                    self._schema.name,
                    call_id or "-",
                    (time.perf_counter() - started) * 1000.0,
                    output,
                )
                return ToolResult(
                    call_id=call_id,
                    name=self._schema.name,
                    output=output,
                    is_error=False,
                )
            except ToolError:
                raise
            except Exception as exc:
                raise ToolError(f"Tool '{self._schema.name}' failed: {exc}") from exc
        except ToolError as exc:
            logger.exception(
                "Tool failed agent=%s tool=%s call_id=%s duration_ms=%.1f source=%s args=%s",
                self._agent_id,
                self._schema.name,
                call_id or "-",
                (time.perf_counter() - started) * 1000.0,
                self._source_file,
                normalized_arguments,
            )
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=str(exc),
                is_error=True,
            )

    def _normalize_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(arguments)
        for name, spec in self._script.inputs.items():
            if name in normalized:
                continue
            if not spec.required:
                normalized[name] = spec.default
        return normalized


async def discover_tools(
    workspace: AgentWorkspace,
    capabilities: dict[str, Any] | None = None,
) -> list[GrailTool]:
    """Discover .pym tools under _bundle/tools in an agent workspace."""
    resolved_capabilities = capabilities or {}
    agent_id = str(getattr(workspace, "_agent_id", "?"))
    try:
        tool_files = await workspace.list_dir("_bundle/tools")
    except (FileNotFoundError, FsdFileNotFoundError):
        logger.info("No tools directory for agent=%s", agent_id)
        return []

    tools: list[GrailTool] = []
    for filename in tool_files:
        if not filename.endswith(".pym"):
            continue
        try:
            source = await workspace.read(f"_bundle/tools/{filename}")
            script = _load_script_from_source(source, filename.removesuffix(".pym"))
            tools.append(
                GrailTool(
                    script=script,
                    capabilities=resolved_capabilities,
                    agent_id=agent_id,
                    source_file=filename,
                    source=source,
                )
            )
        # Error boundary: invalid tool scripts are skipped so other tools still load.
        except (OSError, SyntaxError, ToolError):
            logger.exception("Failed to load tool %s for agent=%s", filename, agent_id)

    logger.debug("Loaded %d Grail tool(s) for agent=%s", len(tools), agent_id)
    return tools


__all__ = ["GrailTool", "discover_tools"]
