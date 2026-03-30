from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer
from tests.factories import make_node

from remora.core.storage.db import open_database
from remora.core.events import EventStore
from remora.core.storage.graph import NodeStore
from remora.lsp.server import (
    DocumentStore,
    _find_node_at_line,
    _node_to_hover,
    _node_to_lens,
    create_lsp_server,
)


@pytest_asyncio.fixture
async def lsp_env(tmp_path: Path):
    db = await open_database(tmp_path / "lsp.db")
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()
    yield node_store, event_store
    await db.close()


def _handlers(server: LanguageServer):
    handlers = getattr(server, "remora_handlers", None)
    assert handlers is not None
    return handlers


@pytest.mark.asyncio
async def test_lsp_server_creates(lsp_env) -> None:
    node_store, event_store = lsp_env
    server = create_lsp_server(node_store, event_store)
    assert isinstance(server, LanguageServer)


@pytest.mark.asyncio
async def test_lsp_server_accepts_shared_services(lsp_env, tmp_path: Path) -> None:
    node_store, event_store = lsp_env
    server = create_lsp_server(node_store=node_store, event_store=event_store)
    handlers = _handlers(server)
    did_save = handlers.did_save

    file_path = tmp_path / "src" / "shared.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("def x():\n    return 1\n", encoding="utf-8")
    await did_save(
        lsp.DidSaveTextDocumentParams(
            text_document=lsp.TextDocumentIdentifier(uri=f"file://{file_path}"),
        )
    )

    events = await event_store.get_events(limit=5)
    assert any(
        event["event_type"] == "content_changed"
        and event["payload"].get("path") == str(file_path)
        for event in events
    )


@pytest.mark.asyncio
async def test_lsp_server_accepts_db_path(tmp_path: Path) -> None:
    db_path = tmp_path / "standalone-lsp.db"
    db = await open_database(db_path)
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()
    await db.close()

    server = create_lsp_server(db_path=db_path)
    handlers = _handlers(server)
    did_save = handlers.did_save

    file_path = tmp_path / "src" / "standalone.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("def y():\n    return 2\n", encoding="utf-8")
    await did_save(
        lsp.DidSaveTextDocumentParams(
            text_document=lsp.TextDocumentIdentifier(uri=f"file://{file_path}"),
        )
    )

    verify_db = await open_database(db_path)
    verify_store = EventStore(db=verify_db)
    rows = await verify_store.get_events(limit=10)
    await verify_db.close()
    assert any(
        event["event_type"] == "content_changed"
        and event["payload"].get("path") == str(file_path)
        for event in rows
    )


def test_node_to_lens() -> None:
    node = make_node("src/app.py::a", file_path="src/app.py", start_line=2, end_line=5)
    lens = _node_to_lens(node)
    assert lens.range.start.line == node.start_line - 1
    assert lens.range.end.line == node.end_line - 1
    assert lens.command is not None
    assert "Remora " in lens.command.title
    assert node.status in lens.command.title


def test_node_to_hover() -> None:
    node = make_node("src/app.py::a", file_path="src/app.py", start_line=2, end_line=5)
    hover = _node_to_hover(
        node,
        callers=["src/app.py::caller"],
        callees=["src/app.py::callee"],
        recent_events=["agent_start"],
    )
    assert isinstance(hover, lsp.Hover)
    assert node.node_id in hover.contents.value
    assert node.file_path in hover.contents.value
    assert "Recent Events" in hover.contents.value
    assert "agent_start" in hover.contents.value


def test_find_node_at_line() -> None:
    node_a = make_node("src/app.py::a", file_path="src/app.py", start_line=2, end_line=5)
    node_b = make_node(
        "src/app.py::b",
        file_path="src/app.py",
        start_line=2,
        end_line=5,
    ).model_copy(update={"start_line": 10, "end_line": 12})
    assert _find_node_at_line([node_a, node_b], 3) == node_a
    assert _find_node_at_line([node_a, node_b], 11) == node_b
    assert _find_node_at_line([node_a, node_b], 99) is None


@pytest.mark.asyncio
async def test_lsp_did_save_emits_event(lsp_env, tmp_path: Path) -> None:
    node_store, event_store = lsp_env
    server = create_lsp_server(node_store, event_store)
    handlers = _handlers(server)
    did_save = handlers.did_save

    file_path = tmp_path / "src" / "app.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("def a():\n    return 1\n", encoding="utf-8")
    params = lsp.DidSaveTextDocumentParams(
        text_document=lsp.TextDocumentIdentifier(uri=f"file://{file_path}"),
    )

    await did_save(params)
    events = await event_store.get_events(limit=5)
    assert events
    assert events[0]["event_type"] == "content_changed"
    assert events[0]["payload"]["path"] == str(file_path)


@pytest.mark.asyncio
async def test_lsp_did_change_writes_file_and_emits_event(
    lsp_env,
    tmp_path: Path,
) -> None:
    node_store, event_store = lsp_env
    server = create_lsp_server(node_store, event_store)
    handlers = _handlers(server)
    did_change = handlers.did_change

    file_path = tmp_path / "src" / "app.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("print('hello')\n", encoding="utf-8")
    change = lsp.TextDocumentContentChangeWholeDocument(
        text="print('goodbye')\n",
    )
    params = lsp.DidChangeTextDocumentParams(
        text_document=lsp.VersionedTextDocumentIdentifier(
            uri=f"file://{file_path}",
            version=2,
        ),
        content_changes=[change],
    )

    await did_change(params)
    documents = handlers.documents
    assert isinstance(documents, DocumentStore)
    assert documents.get(f"file://{file_path}") == "print('goodbye')\n"
    events = await event_store.get_events(limit=5)
    assert not any(
        event["event_type"] == "content_changed"
        and event["payload"].get("path") == str(file_path)
        and event["payload"].get("change_type") == "modified"
        for event in events
    )


@pytest.mark.asyncio
async def test_lsp_open_change_save_lifecycle(lsp_env, tmp_path: Path) -> None:
    node_store, event_store = lsp_env
    server = create_lsp_server(node_store, event_store)
    handlers = _handlers(server)
    did_open = handlers.did_open
    did_change = handlers.did_change
    did_save = handlers.did_save
    documents = handlers.documents

    file_path = tmp_path / "src" / "lifecycle.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    uri = f"file://{file_path}"

    await did_open(
        lsp.DidOpenTextDocumentParams(
            text_document=lsp.TextDocumentItem(
                uri=uri,
                language_id="python",
                version=1,
                text="print('hello')\n",
            )
        )
    )
    await did_change(
        lsp.DidChangeTextDocumentParams(
            text_document=lsp.VersionedTextDocumentIdentifier(uri=uri, version=2),
            content_changes=[lsp.TextDocumentContentChangeWholeDocument(text="print('goodbye')\n")],
        )
    )
    await did_save(
        lsp.DidSaveTextDocumentParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
        )
    )

    assert isinstance(documents, DocumentStore)
    assert documents.get(uri) == "print('goodbye')\n"
    events = await event_store.get_events(limit=20)
    paths = [
        (event["event_type"], event["payload"].get("path"), event["payload"].get("change_type"))
        for event in events
    ]
    assert ("content_changed", str(file_path), "opened") in paths
    assert ("content_changed", str(file_path), "modified") in paths


@pytest.mark.asyncio
async def test_lsp_code_action_returns_chat_and_trigger(lsp_env, tmp_path: Path) -> None:
    node_store, event_store = lsp_env
    file_path = tmp_path / "src" / "actions.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("def act():\n    return 1\n", encoding="utf-8")
    await node_store.upsert_node(
        make_node(
            "src/actions.py::act",
            file_path=str(file_path),
            start_line=1,
            end_line=2,
        )
    )

    server = create_lsp_server(node_store, event_store)
    handlers = _handlers(server)
    code_action = handlers.code_action

    result = await code_action(
        lsp.CodeActionParams(
            text_document=lsp.TextDocumentIdentifier(uri=f"file://{file_path}"),
            range=lsp.Range(
                start=lsp.Position(line=0, character=0),
                end=lsp.Position(line=0, character=1),
            ),
            context=lsp.CodeActionContext(diagnostics=[]),
        )
    )
    titles = [action.title for action in result]
    commands = [action.command.command if action.command is not None else "" for action in result]
    assert "Remora: Open Chat Panel" in titles
    assert "Remora: Trigger Agent" in titles
    assert "remora.chat" in commands
    assert "remora.trigger" in commands


@pytest.mark.asyncio
async def test_lsp_trigger_command_emits_agent_message_event(lsp_env) -> None:
    node_store, event_store = lsp_env
    server = create_lsp_server(node_store, event_store)
    handlers = _handlers(server)
    trigger_command = handlers.trigger_command

    await trigger_command(server, ["src/app.py::a"])
    events = await event_store.get_events(limit=5)
    assert any(
        event["event_type"] == "agent_message"
        and event["payload"].get("to_agent") == "src/app.py::a"
        and event["payload"].get("content") == "Manual trigger from editor"
        for event in events
    )


@pytest.mark.asyncio
async def test_lsp_chat_command_requests_external_document(lsp_env) -> None:
    node_store, event_store = lsp_env
    server = create_lsp_server(node_store, event_store)
    handlers = _handlers(server)
    chat_command = handlers.chat_command

    shown: dict[str, object] = {}

    def fake_show_document(params):  # noqa: ANN001, ANN202
        shown["uri"] = params.uri
        shown["external"] = params.external

    server.show_document = fake_show_document  # type: ignore[assignment]
    await chat_command(server, ["src/app.py::a"])

    assert shown["uri"] == "http://localhost:8080/?node=src/app.py::a"
    assert shown["external"] is True


@pytest.mark.asyncio
async def test_lsp_chat_command_uses_configured_web_port(lsp_env) -> None:
    node_store, event_store = lsp_env
    server = create_lsp_server(node_store, event_store, web_port=8765)
    handlers = _handlers(server)
    chat_command = handlers.chat_command

    shown: dict[str, object] = {}

    def fake_show_document(params):  # noqa: ANN001, ANN202
        shown["uri"] = params.uri
        shown["external"] = params.external

    server.show_document = fake_show_document  # type: ignore[assignment]
    await chat_command(server, ["src/app.py::a"])

    assert shown["uri"] == "http://localhost:8765/?node=src/app.py::a"
    assert shown["external"] is True
