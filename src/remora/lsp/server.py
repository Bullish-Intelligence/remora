"""Thin pygls adapter for Remora graph data and events."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

from remora.core.storage.db import open_database
from remora.core.events import (
    AgentMessageEvent,
    ContentChangedEvent,
    EventBus,
    SubscriptionRegistry,
    TriggerDispatcher,
)
from remora.core.events.store import EventStore
from remora.core.storage.graph import NodeStore
from remora.core.model.node import Node
from remora.core.storage.transaction import TransactionContext
from remora.core.model.types import ChangeType, serialize_enum

_STATUS_ICONS = {
    "idle": "○",
    "running": "▶",
    "awaiting_input": "⏸",
    "awaiting_review": "⏳",
    "error": "✗",
}


class DocumentStore:
    """In-memory document text tracked by the LSP server."""

    def __init__(self) -> None:
        self._documents: dict[str, str] = {}

    def open(self, uri: str, text: str) -> None:
        self._documents[uri] = text

    def close(self, uri: str) -> None:
        self._documents.pop(uri, None)

    def get(self, uri: str) -> str | None:
        return self._documents.get(uri)

    def apply_changes(
        self,
        uri: str,
        changes: Sequence[lsp.TextDocumentContentChangeEvent],
    ) -> str:
        text = self._documents.get(uri, "")
        for change in changes:
            change_text = getattr(change, "text", "") or ""
            range_value = getattr(change, "range", None)
            if range_value is None:
                text = change_text
                continue
            start = _position_to_offset(text, range_value.start)
            end = _position_to_offset(text, range_value.end)
            text = text[:start] + change_text + text[end:]
        self._documents[uri] = text
        return text


@dataclass(frozen=True)
class RemoraLSPHandlers:
    """Typed references to test-facing handler callables and document state."""

    code_lens: Any
    hover: Any
    did_save: Any
    did_open: Any
    did_close: Any
    did_change: Any
    code_action: Any
    chat_command: Any
    trigger_command: Any
    documents: DocumentStore


class RemoraLanguageServer(LanguageServer):
    """LanguageServer with an explicit test handler abstraction slot."""

    def __init__(self, name: str, version: str) -> None:
        super().__init__(name, version)
        self.remora_handlers: RemoraLSPHandlers | None = None


def create_lsp_server(
    node_store: NodeStore | None = None,
    event_store: EventStore | None = None,
    db_path: Path | None = None,
    web_port: int = 8080,
) -> LanguageServer:
    """Create an LSP server from shared stores or a standalone sqlite path."""
    server = RemoraLanguageServer("remora", "2.0.0")
    documents = DocumentStore()
    stores: dict[str, Any] = {}

    async def get_stores() -> tuple[NodeStore, EventStore]:
        if node_store is not None and event_store is not None:
            return node_store, event_store
        if db_path is None:
            raise RuntimeError("create_lsp_server requires shared stores or db_path")
        if "node_store" not in stores or "event_store" not in stores:
            opened_node_store, opened_event_store = await _open_standalone_stores(db_path)
            stores["node_store"] = opened_node_store
            stores["event_store"] = opened_event_store
        return stores["node_store"], stores["event_store"]

    @server.feature(lsp.TEXT_DOCUMENT_CODE_LENS)
    async def code_lens(params: lsp.CodeLensParams) -> list[lsp.CodeLens]:
        current_node_store, _event_store = await get_stores()
        file_path = _uri_to_path(params.text_document.uri)
        nodes = await current_node_store.list_nodes(file_path=file_path)
        return [_node_to_lens(node) for node in nodes]

    @server.feature(lsp.TEXT_DOCUMENT_HOVER)
    async def hover(params: lsp.HoverParams) -> lsp.Hover | None:
        current_node_store, current_event_store = await get_stores()
        file_path = _uri_to_path(params.text_document.uri)
        nodes = await current_node_store.list_nodes(file_path=file_path)
        node = _find_node_at_line(nodes, params.position.line + 1)
        if node is None:
            return None
        edges = await current_node_store.get_edges(node.node_id, direction="both")
        callers = sorted({edge.from_id for edge in edges if edge.to_id == node.node_id})
        callees = sorted({edge.to_id for edge in edges if edge.from_id == node.node_id})
        recent_rows = await current_event_store.get_events_for_agent(node.node_id, limit=5)
        recent_events = [
            str(row.get("event_type", "")) for row in recent_rows if row.get("event_type")
        ]
        return _node_to_hover(node, callers=callers, callees=callees, recent_events=recent_events)

    @server.feature(lsp.TEXT_DOCUMENT_CODE_ACTION)
    async def code_action(params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
        current_node_store, _event_store = await get_stores()
        file_path = _uri_to_path(params.text_document.uri)
        nodes = await current_node_store.list_nodes(file_path=file_path)
        node = _find_node_at_line(nodes, params.range.start.line + 1)
        if node is None:
            return []
        return _node_to_actions(node.node_id)

    @server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
    async def did_save(params: lsp.DidSaveTextDocumentParams) -> None:
        _node_store, current_event_store = await get_stores()
        file_path = _uri_to_path(params.text_document.uri)
        await current_event_store.append(
            ContentChangedEvent(path=file_path, change_type=ChangeType.MODIFIED)
        )

    @server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
    async def did_open(params: lsp.DidOpenTextDocumentParams) -> None:
        _node_store, current_event_store = await get_stores()
        documents.open(params.text_document.uri, params.text_document.text)
        file_path = _uri_to_path(params.text_document.uri)
        await current_event_store.append(
            ContentChangedEvent(path=file_path, change_type=ChangeType.OPENED)
        )

    @server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
    async def did_close(params: lsp.DidCloseTextDocumentParams) -> None:
        documents.close(params.text_document.uri)

    @server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
    async def did_change(params: lsp.DidChangeTextDocumentParams) -> None:
        documents.apply_changes(params.text_document.uri, params.content_changes)

    @server.command("remora.chat")
    async def chat_command(ls: LanguageServer, args: list[Any]) -> None:
        node_id = str(args[0]).strip() if args else ""
        if not node_id:
            return
        ls.show_document(
            lsp.ShowDocumentParams(
                uri=f"http://localhost:{web_port}/?node={node_id}",
                external=True,
            )
        )

    @server.command("remora.trigger")
    async def trigger_command(ls: LanguageServer, args: list[Any]) -> None:
        del ls
        node_id = str(args[0]).strip() if args else ""
        if not node_id:
            return
        _node_store, current_event_store = await get_stores()
        await current_event_store.append(
            AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content="Manual trigger from editor",
            )
        )

    # Expose handlers for direct unit testing without spinning up an LSP transport.
    server.remora_handlers = RemoraLSPHandlers(
        code_lens=code_lens,
        hover=hover,
        did_save=did_save,
        did_open=did_open,
        did_close=did_close,
        did_change=did_change,
        code_action=code_action,
        chat_command=chat_command,
        trigger_command=trigger_command,
        documents=documents,
    )

    return server


async def _open_standalone_stores(db_path: Path) -> tuple[NodeStore, EventStore]:
    """Open stores backed by a shared Remora database path."""
    db = await open_database(db_path)
    event_bus = EventBus()
    dispatcher = TriggerDispatcher()
    tx = TransactionContext(db, event_bus, dispatcher)
    subscriptions = SubscriptionRegistry(db, tx=tx)
    dispatcher.subscriptions = subscriptions
    node_store = NodeStore(db, tx=tx)
    event_store = EventStore(
        db=db,
        event_bus=event_bus,
        dispatcher=dispatcher,
        tx=tx,
    )
    return node_store, event_store


def create_lsp_server_standalone(db_path: Path) -> LanguageServer:
    """Create an LSP server that lazily opens stores from a sqlite DB path."""
    return create_lsp_server(db_path=db_path)


def _node_to_lens(node: Node) -> lsp.CodeLens:
    """Map a Node to a CodeLens entry showing runtime status."""
    status = serialize_enum(node.status)
    icon = _STATUS_ICONS.get(status, "○")
    return lsp.CodeLens(
        range=lsp.Range(
            start=lsp.Position(line=max(0, node.start_line - 1), character=0),
            end=lsp.Position(line=max(0, node.end_line - 1), character=0),
        ),
        command=lsp.Command(
            title=f"Remora {icon} {status}",
            command="remora.showNode",
            arguments=[node.node_id],
        ),
        data={"node_id": node.node_id},
    )


def _node_to_hover(
    node: Node,
    *,
    callers: list[str] | None = None,
    callees: list[str] | None = None,
    recent_events: list[str] | None = None,
) -> lsp.Hover:
    """Map a Node to markdown hover details."""
    node_type = serialize_enum(node.node_type)
    status = serialize_enum(node.status)
    caller_ids = callers or []
    callee_ids = callees or []
    event_names = recent_events or []
    recent_events_block = (
        "\n".join(f"- `{event_name}`" for event_name in event_names) if event_names else "- _none_"
    )
    value = (
        f"### {node.full_name}\n"
        f"- Node ID: `{node.node_id}`\n"
        f"- Type: `{node_type}`\n"
        f"- Status: `{status}`\n"
        f"- File: `{node.file_path}:{node.start_line}-{node.end_line}`\n"
        f"- Parent: `{node.parent_id or '-'}`\n"
        f"- Callers: `{len(caller_ids)}`\n"
        f"- Callees: `{len(callee_ids)}`\n"
        "#### Recent Events\n"
        f"{recent_events_block}"
    )
    return lsp.Hover(
        contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=value,
        )
    )


def _node_to_actions(node_id: str) -> list[lsp.CodeAction]:
    return [
        lsp.CodeAction(
            title="Remora: Open Chat Panel",
            kind=lsp.CodeActionKind.Refactor,
            command=lsp.Command(
                title="Open Chat Panel",
                command="remora.chat",
                arguments=[node_id],
            ),
        ),
        lsp.CodeAction(
            title="Remora: Trigger Agent",
            kind=lsp.CodeActionKind.QuickFix,
            command=lsp.Command(
                title="Trigger Agent",
                command="remora.trigger",
                arguments=[node_id],
            ),
        ),
    ]


def _find_node_at_line(nodes: list[Node], line: int) -> Node | None:
    """Find the narrowest node whose range contains the provided 1-based line."""
    containing = [node for node in nodes if node.start_line <= line <= node.end_line]
    if not containing:
        return None
    return min(containing, key=lambda node: node.end_line - node.start_line)


def _uri_to_path(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return str(Path(unquote(parsed.path)))
    return uri


def _position_to_offset(text: str, position: lsp.Position) -> int:
    lines = text.splitlines(keepends=True)
    if not lines:
        lines = [""]
    line_index = min(position.line, len(lines) - 1)
    offset = sum(len(line) for line in lines[:line_index])
    line_text = lines[line_index]
    char_index = min(position.character, len(line_text))
    return offset + char_index


__all__ = ["create_lsp_server", "create_lsp_server_standalone"]
