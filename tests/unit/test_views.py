from __future__ import annotations

from pathlib import Path


def _index_html() -> str:
    return Path("src/remora/web/static/index.html").read_text(encoding="utf-8")


def _main_js() -> str:
    return Path("src/remora/web/static/main.js").read_text(encoding="utf-8")


def test_graph_html_renders() -> None:
    html = _index_html()
    assert isinstance(html, str)
    assert html.strip()
    assert '<div id="graph"' in html
    assert "Remora" in html


def test_graph_html_uses_module_bootstrap() -> None:
    html = _index_html()
    assert '<script type="module" src="/static/main.js"></script>' in html


def test_graph_html_uses_vendored_script_paths() -> None:
    html = _index_html()
    assert '<script src="/static/vendor/graphology.umd.min.js"></script>' in html
    assert '<script src="/static/vendor/sigma.min.js"></script>' in html
    assert "unpkg.com" not in html


def test_graph_html_includes_focus_pin_search_controls() -> None:
    html = _index_html()
    assert 'data-focus-mode="full"' in html
    assert 'data-focus-mode="hop1"' in html
    assert 'data-focus-mode="hop2"' in html
    assert 'data-pin-toggle="selected"' in html
    assert 'id="node-search"' in html
    assert 'id="search-go"' in html


def test_main_js_bootstraps_sse_and_runtime_globals() -> None:
    js = _main_js()
    assert 'events.start("/sse")' in js
    assert "globalThis.graph = graph;" in js
    assert "globalThis.renderer = rendererApi.renderer;" in js
    assert "globalThis.nodeLabelHitboxes = nodeLabelHitboxes;" in js
    assert "globalThis.__remora_layout_metrics = runtimeMetrics;" in js


def test_main_js_uses_incremental_update_path_for_discovery() -> None:
    js = _main_js()
    assert "async function upsertNodeIncremental(" in js
    assert 'if (type === "node_discovered") {' in js
    assert "await upsertNodeIncremental(payload.node_id" in js
    assert "graphState.applySnapshot(nodes, edges);" in js
    assert "graph.clear()" not in js


def test_main_js_uses_graph_state_layout_and_interaction_modules() -> None:
    js = _main_js()
    assert 'import { createGraphState } from "./graph-state.js";' in js
    assert 'import { createLayoutEngine } from "./layout-engine.js";' in js
    assert 'import { createInteractions } from "./interactions.js";' in js
    assert 'import { createEventStream } from "./events.js";' in js
    assert "layoutEngine.runInitialLayout(" in js
    assert "layoutEngine.reheatLayout(" in js
