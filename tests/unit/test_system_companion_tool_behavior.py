from __future__ import annotations

from pathlib import Path

import grail
import pytest

TOOLS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "remora"
    / "defaults"
    / "bundles"
    / "system"
    / "tools"
)


def _load_tool(name: str) -> grail.GrailScript:
    return grail.load(TOOLS_DIR / f"{name}.pym")


@pytest.mark.asyncio
async def test_companion_summarize_writes_bounded_chat_index_and_supports_string_list_tags(
) -> None:
    script = _load_tool("companion_summarize")
    kv_store: dict[str, object] = {
        "companion/chat_index": [{"summary": f"old-{idx}"} for idx in range(55)],
    }

    async def kv_get(key: str) -> object:
        return kv_store.get(key)

    async def kv_set(key: str, value: object) -> None:
        kv_store[key] = value

    async def my_correlation_id() -> str:
        return "corr-companion-summary"

    first_result = await script.run(
        inputs={"summary": "Found two risky joins", "tags": "review, db"},
        externals={
            "kv_get": kv_get,
            "kv_set": kv_set,
            "my_correlation_id": my_correlation_id,
        },
    )
    assert "Recorded summary" in str(first_result)
    chat_index = kv_store["companion/chat_index"]
    assert isinstance(chat_index, list)
    assert len(chat_index) == 50
    assert chat_index[-1]["summary"] == "Found two risky joins"
    assert chat_index[-1]["tags"] == ["review", "db"]
    assert chat_index[-1]["correlation_id"] == "corr-companion-summary"

    second_result = await script.run(
        inputs={"summary": "Follow-up summary", "tags": ["incident", "triage"]},
        externals={
            "kv_get": kv_get,
            "kv_set": kv_set,
            "my_correlation_id": my_correlation_id,
        },
    )
    assert "incident" in str(second_result)
    chat_index = kv_store["companion/chat_index"]
    assert isinstance(chat_index, list)
    assert chat_index[-1]["tags"] == ["incident", "triage"]


@pytest.mark.asyncio
async def test_companion_reflect_appends_reflection_with_correlation_id() -> None:
    script = _load_tool("companion_reflect")
    kv_store: dict[str, object] = {
        "companion/reflections": [{"insight": f"old-{idx}"} for idx in range(29)],
    }

    async def kv_get(key: str) -> object:
        return kv_store.get(key)

    async def kv_set(key: str, value: object) -> None:
        kv_store[key] = value

    async def my_correlation_id() -> str:
        return "corr-companion-reflect"

    result = await script.run(
        inputs={"insight": "Need additional validation around retries"},
        externals={
            "kv_get": kv_get,
            "kv_set": kv_set,
            "my_correlation_id": my_correlation_id,
        },
    )

    assert "Recorded reflection" in str(result)
    reflections = kv_store["companion/reflections"]
    assert isinstance(reflections, list)
    assert len(reflections) == 30
    assert reflections[-1] == {
        "correlation_id": "corr-companion-reflect",
        "insight": "Need additional validation around retries",
    }


@pytest.mark.asyncio
async def test_companion_link_deduplicates_and_preserves_relationship_metadata() -> None:
    script = _load_tool("companion_link")
    kv_store: dict[str, object] = {"companion/links": []}
    set_calls = 0

    async def kv_get(key: str) -> object:
        return kv_store.get(key)

    async def kv_set(key: str, value: object) -> None:
        nonlocal set_calls
        set_calls += 1
        kv_store[key] = value

    async def my_correlation_id() -> str:
        return "corr-companion-link"

    first_result = await script.run(
        inputs={"target_node_id": "src/api/orders.py::create_order"},
        externals={
            "kv_get": kv_get,
            "kv_set": kv_set,
            "my_correlation_id": my_correlation_id,
        },
    )
    assert "Linked to src/api/orders.py::create_order" in str(first_result)
    links = kv_store["companion/links"]
    assert isinstance(links, list)
    assert links == [
        {
            "target": "src/api/orders.py::create_order",
            "relationship": "related",
            "correlation_id": "corr-companion-link",
        }
    ]
    assert set_calls == 1

    second_result = await script.run(
        inputs={"target_node_id": "src/api/orders.py::create_order"},
        externals={
            "kv_get": kv_get,
            "kv_set": kv_set,
            "my_correlation_id": my_correlation_id,
        },
    )
    assert "Already linked" in str(second_result)
    assert set_calls == 1


@pytest.mark.asyncio
async def test_summarize_writes_notes_summary_from_event_history() -> None:
    script = _load_tool("summarize")
    writes: dict[str, str] = {}

    async def event_get_history(target_id: str, limit: int) -> list[dict]:
        assert target_id == "src/app.py::alpha"
        assert limit == 5
        return [
            {"event_type": "agent_start", "summary": "Started work"},
            {"event_type": "agent_complete", "summary": "Finished successfully"},
        ]

    async def write_file(path: str, content: str) -> None:
        writes[path] = content

    result = await script.run(
        inputs={"node_id": "src/app.py::alpha", "history_limit": 5},
        externals={
            "event_get_history": event_get_history,
            "write_file": write_file,
        },
    )

    assert result == "Summary updated"
    assert "notes/summary.md" in writes
    content = writes["notes/summary.md"]
    assert "# Recent Activity Summary" in content
    assert "- agent_start: Started work" in content
    assert "- agent_complete: Finished successfully" in content


@pytest.mark.asyncio
async def test_find_links_writes_meta_links_from_graph_edges() -> None:
    script = _load_tool("find_links")
    writes: dict[str, str] = {}

    async def graph_get_edges(target_id: str) -> list[dict]:
        assert target_id == "src/app.py::alpha"
        return [
            {
                "from_id": "src/app.py::alpha",
                "to_id": "src/data.py::fetch",
                "edge_type": "calls",
            },
            {
                "from_id": "src/app.py::alpha",
                "to_id": "src/models.py::Order",
                "edge_type": "uses",
            },
        ]

    async def write_file(path: str, content: str) -> None:
        writes[path] = content

    result = await script.run(
        inputs={"node_id": "src/app.py::alpha"},
        externals={
            "graph_get_edges": graph_get_edges,
            "write_file": write_file,
        },
    )

    assert result == "Recorded 2 links"
    assert "meta/links.md" in writes
    content = writes["meta/links.md"]
    assert "# Links" in content
    assert "- calls: src/app.py::alpha -> src/data.py::fetch" in content
    assert "- uses: src/app.py::alpha -> src/models.py::Order" in content


@pytest.mark.asyncio
async def test_categorize_writes_meta_categories_with_deterministic_category() -> None:
    script = _load_tool("categorize")
    writes: dict[str, str] = {}

    async def graph_get_node(target_id: str) -> dict | None:
        assert target_id == "src/tests/test_orders.py::test_create_order"
        return {
            "node_type": "function",
            "source_code": "def test_create_order():\n    assert request.status_code == 200\n",
        }

    async def write_file(path: str, content: str) -> None:
        writes[path] = content

    result = await script.run(
        inputs={"node_id": "src/tests/test_orders.py::test_create_order"},
        externals={
            "graph_get_node": graph_get_node,
            "write_file": write_file,
        },
    )

    assert result == "Categorization updated: testing"
    assert "meta/categories.md" in writes
    content = writes["meta/categories.md"]
    assert "# Categories" in content
    assert "Type: function" in content
    assert "Primary: testing" in content
