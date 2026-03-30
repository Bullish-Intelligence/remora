from __future__ import annotations

import asyncio
import contextlib
import socket
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
import pytest_asyncio
from tests.factories import write_file

from remora.__main__ import _configure_file_logging
from remora.core.model.config import load_config
from remora.core.services.lifecycle import RemoraLifecycle

playwright = pytest.importorskip("playwright.async_api")
expect = playwright.expect


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_graph_ui_project(root: Path) -> Path:
    write_file(
        root / "src" / "pricing.py",
        (
            "def apply_tax_rate(amount: float, rate: float = 0.07) -> float:\n"
            "    return amount * (1 + rate)\n\n"
            "def discount_for_tier(amount: float, tier: str = \"standard\") -> float:\n"
            "    return amount * (0.9 if tier == \"vip\" else 0.97)\n"
        ),
    )
    write_file(
        root / "src" / "orders.py",
        (
            "from pricing import apply_tax_rate, discount_for_tier\n"
            "from legacy_helpers import legacy_discount\n"
            "from observers.audit import AuditObserver\n\n"
            "class Order:\n"
            "    def total(self, subtotal: float) -> float:\n"
            "        discounted = discount_for_tier(subtotal, \"vip\")\n"
            "        taxed = apply_tax_rate(discounted)\n"
            "        observed = AuditObserver().notify(\"computed\")\n"
            "        if observed:\n"
            "            taxed = legacy_discount(taxed)\n"
            "        return round(taxed, 2)\n\n"
            "def apply_tax(amount: float) -> float:\n"
            "    return apply_tax_rate(amount)\n"
        ),
    )
    write_file(
        root / "src" / "legacy_helpers.py",
        (
            "def legacy_discount(amount: float) -> float:\n"
            "    return amount * 0.95\n"
        ),
    )
    write_file(
        root / "src" / "observers" / "__init__.py",
        "",
    )
    write_file(
        root / "src" / "observers" / "audit.py",
        (
            "class AuditObserver:\n"
            "    def notify(self, event: str) -> str:\n"
            "        return f\"audit:{event}\"\n"
        ),
    )

    bundles_root = root / "bundles"
    system = bundles_root / "system"
    code = bundles_root / "code-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (code / "tools").mkdir(parents=True, exist_ok=True)
    write_file(system / "bundle.yaml", "name: system\nmax_turns: 4\n")
    write_file(code / "bundle.yaml", "name: code-agent\nmax_turns: 4\n")

    config_path = root / "remora.yaml"
    config_path.write_text(
        (
            "discovery_paths:\n"
            "  - src\n"
            "discovery_languages:\n"
            "  - python\n"
            "language_map:\n"
            "  .py: python\n"
            "query_search_paths:\n"
            "  - \"@default\"\n"
            "workspace_root: .remora-web-acceptance\n"
            "bundle_search_paths:\n"
            f"  - {bundles_root}\n"
            "  - \"@default\"\n"
            "max_turns: 4\n"
        ),
        encoding="utf-8",
    )
    return config_path


async def _wait_for_health(base_url: str, timeout_s: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(base_url=base_url, timeout=2.0) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get("/api/health")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
    raise AssertionError(f"Runtime at {base_url} did not become healthy within {timeout_s}s")


async def _wait_for_nodes(base_url: str, timeout_s: float = 20.0) -> list[dict]:
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(base_url=base_url, timeout=2.0) as client:
        while time.monotonic() < deadline:
            response = await client.get("/api/nodes")
            if response.status_code == 200:
                payload = response.json()
                if isinstance(payload, list) and payload:
                    return payload
            await asyncio.sleep(0.2)
    raise AssertionError("Timed out waiting for discovered graph nodes")


async def _wait_for_event(
    base_url: str,
    predicate,
    *,
    timeout_s: float = 20.0,
) -> dict:
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(base_url=base_url, timeout=2.0) as client:
        while time.monotonic() < deadline:
            response = await client.get("/api/events?limit=200")
            assert response.status_code == 200
            payload = response.json()
            assert isinstance(payload, list)
            for event in payload:
                if predicate(event):
                    return event
            await asyncio.sleep(0.2)
    raise AssertionError("Timed out waiting for matching event")


@contextlib.asynccontextmanager
async def _running_runtime(*, project_root: Path, config_path: Path, port: int):
    config = load_config(config_path)
    lifecycle = RemoraLifecycle(
        config=config,
        project_root=project_root,
        bind="127.0.0.1",
        port=port,
        no_web=False,
        log_events=False,
        lsp=False,
        configure_file_logging=_configure_file_logging,
    )
    base_url = f"http://127.0.0.1:{port}"
    await lifecycle.start()
    await _wait_for_health(base_url)
    try:
        yield base_url
    finally:
        await asyncio.wait_for(lifecycle.shutdown(), timeout=20.0)


@pytest_asyncio.fixture
async def chromium_page():
    try:
        async with playwright.async_playwright() as session:
            browser = await session.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1400, "height": 900})
            page = await context.new_page()
            try:
                yield page
            finally:
                await context.close()
                await browser.close()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Playwright/Chromium unavailable: {exc}")


@pytest.mark.asyncio
@pytest.mark.acceptance
async def test_web_graph_clicking_label_hitbox_selects_node_and_updates_sidebar(
    tmp_path: Path,
    chromium_page,
) -> None:
    config_path = _write_graph_ui_project(tmp_path)
    port = _reserve_port()

    async with _running_runtime(
        project_root=tmp_path,
        config_path=config_path,
        port=port,
    ) as base_url:
        await _wait_for_nodes(base_url)
        page = chromium_page
        await page.goto(base_url, wait_until="domcontentloaded")
        await page.wait_for_selector("#graph canvas")
        await page.wait_for_function(
            "() => typeof nodeLabelHitboxes !== 'undefined' && nodeLabelHitboxes.size > 0",
            timeout=20000,
        )

        selection = await page.evaluate(
            """
            async () => {
              if (typeof nodeLabelHitboxes === "undefined") return null;
              if (typeof graph === "undefined") return null;
              if (typeof renderer === "undefined") return null;
              const ratio = renderer.getRenderParams().pixelRatio || window.devicePixelRatio || 1;
              for (const [nodeId, box] of nodeLabelHitboxes.entries()) {
                if (!graph.hasNode(nodeId)) continue;
                if (graph.getNodeAttribute(nodeId, "node_type") === "__label__") continue;
                const response = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}`);
                if (!response.ok) continue;
                const node = await response.json();
                return {
                  nodeId,
                  fullName: String(node.full_name || ""),
                  x: (box.x + box.width / 2) / ratio,
                  y: (box.y + box.height / 2) / ratio
                };
              }
              return null;
            }
            """
        )

        assert selection is not None
        assert selection["nodeId"]
        assert selection["fullName"]
        graph_box = await page.locator("#graph").bounding_box()
        assert graph_box is not None
        click_x = max(5.0, min(float(selection["x"]), graph_box["width"] - 5.0))
        click_y = max(5.0, min(float(selection["y"]), graph_box["height"] - 5.0))
        await page.locator("#graph").click(position={"x": click_x, "y": click_y})

        await expect(page.locator("#node-name")).to_have_text(selection["fullName"], timeout=15000)
        await expect(page.locator("#agent-header")).to_contain_text(selection["fullName"])


@pytest.mark.asyncio
@pytest.mark.acceptance
async def test_web_graph_has_visible_nodes_in_viewport_after_initial_load(
    tmp_path: Path,
    chromium_page,
) -> None:
    config_path = _write_graph_ui_project(tmp_path)
    port = _reserve_port()

    async with _running_runtime(
        project_root=tmp_path,
        config_path=config_path,
        port=port,
    ) as base_url:
        await _wait_for_nodes(base_url)
        page = chromium_page
        await page.goto(base_url, wait_until="domcontentloaded")
        await page.wait_for_selector("#graph canvas")
        await page.wait_for_function(
            "() => typeof graph !== 'undefined' && graph.order >= 2",
            timeout=20000,
        )
        await page.wait_for_function(
            "() => typeof window.__remora_layout_metrics === 'object' && !!window.__remora_layout_metrics && window.__remora_layout_metrics.ready === true",
            timeout=20000,
        )
        baseline = await page.evaluate(
            """
            () => {
              const dims = renderer.getDimensions();
              let total = 0;
              let visible = 0;
              let minVX = Number.POSITIVE_INFINITY;
              let minVY = Number.POSITIVE_INFINITY;
              let maxVX = Number.NEGATIVE_INFINITY;
              let maxVY = Number.NEGATIVE_INFINITY;
              const points = [];
              for (const nodeId of graph.nodes()) {
                const attrs = graph.getNodeAttributes(nodeId);
                if (attrs.hidden) continue;
                total += 1;
                const p = renderer.graphToViewport({ x: attrs.x, y: attrs.y });
                if (p.x >= 0 && p.x <= dims.width && p.y >= 0 && p.y <= dims.height) {
                  visible += 1;
                  minVX = Math.min(minVX, p.x);
                  minVY = Math.min(minVY, p.y);
                  maxVX = Math.max(maxVX, p.x);
                  maxVY = Math.max(maxVY, p.y);
                }
                points.push({ x: p.x, y: p.y });
              }
              let nearestSum = 0;
              for (let i = 0; i < points.length; i += 1) {
                let nearest = Number.POSITIVE_INFINITY;
                for (let j = 0; j < points.length; j += 1) {
                  if (i === j) continue;
                  const dx = points[i].x - points[j].x;
                  const dy = points[i].y - points[j].y;
                  const d = Math.sqrt(dx * dx + dy * dy);
                  if (d < nearest) nearest = d;
                }
                if (Number.isFinite(nearest)) nearestSum += nearest;
              }
              const spanW = Number.isFinite(minVX) && Number.isFinite(maxVX) ? Math.max(0, maxVX - minVX) : 0;
              const spanH = Number.isFinite(minVY) && Number.isFinite(maxVY) ? Math.max(0, maxVY - minVY) : 0;
              const spanXRatio = dims.width > 0 ? spanW / dims.width : 0;
              const spanYRatio = dims.height > 0 ? spanH / dims.height : 0;
              const spreadAreaRatio = dims.width > 0 && dims.height > 0 ? (spanW * spanH) / (dims.width * dims.height) : 0;
              const avgNearest = points.length > 1 ? nearestSum / points.length : 0;
              const cameraRatio = Number(renderer.getCamera().getState().ratio || 0);
              const labeledVisible = typeof nodeLabelHitboxes === "undefined" ? 0 : nodeLabelHitboxes.size;
              const labelCoverage = visible > 0 ? labeledVisible / visible : 0;
              return {
                total,
                visible,
                spanXRatio,
                spanYRatio,
                spreadAreaRatio,
                avgNearest,
                cameraRatio,
                labelCoverage,
                mode: window.__remora_layout_metrics?.mode ?? null,
                ready: window.__remora_layout_metrics?.ready === true,
                fullReloadCount: Number(window.__remora_layout_metrics?.full_reload_count ?? -1),
                hasFocusFull: !!document.querySelector('[data-focus-mode="full"]'),
                hasFocusHop1: !!document.querySelector('[data-focus-mode="hop1"]'),
                hasFocusHop2: !!document.querySelector('[data-focus-mode="hop2"]'),
                hasPinToggle: !!document.querySelector('[data-pin-toggle="selected"]'),
                hasSearch: !!document.getElementById("node-search"),
              };
            }
            """
        )

        assert baseline["total"] > 0, baseline
        assert baseline["visible"] > 0, baseline
        assert baseline["mode"] == "graph", baseline
        assert baseline["ready"] is True, baseline
        assert baseline["fullReloadCount"] == 1, baseline
        assert baseline["hasFocusFull"] is True, baseline
        assert baseline["hasFocusHop1"] is True, baseline
        assert baseline["hasFocusHop2"] is True, baseline
        assert baseline["hasPinToggle"] is True, baseline
        assert baseline["hasSearch"] is True, baseline
        assert baseline["visible"] <= baseline["total"], baseline
        assert baseline["spanXRatio"] >= 0.38, baseline
        assert baseline["spanYRatio"] >= 0.38, baseline
        assert baseline["spreadAreaRatio"] >= 0.27, baseline
        assert baseline["avgNearest"] >= 48, baseline
        assert baseline["cameraRatio"] >= 1.2, baseline
        assert baseline["labelCoverage"] >= 0.42, baseline

        sidebar_before = await page.evaluate(
            """
            () => ({
              hasSummaryNodes: !!document.getElementById("summary-visible-nodes"),
              hasSummaryEdges: !!document.getElementById("summary-visible-edges"),
              hasSummaryThinning: !!document.getElementById("summary-hidden-thinning"),
              hasSummaryFocus: !!document.getElementById("summary-focus-mode"),
              hasQuickPin: !!document.getElementById("quick-pin-toggle"),
              hasQuickFull: !!document.getElementById("quick-focus-full"),
              hasQuickHop1: !!document.getElementById("quick-focus-hop1"),
              hasQuickHop2: !!document.getElementById("quick-focus-hop2"),
              quickPinDisabled: !!document.getElementById("quick-pin-toggle")?.disabled,
            })
            """
        )
        assert sidebar_before["hasSummaryNodes"] is True, sidebar_before
        assert sidebar_before["hasSummaryEdges"] is True, sidebar_before
        assert sidebar_before["hasSummaryThinning"] is True, sidebar_before
        assert sidebar_before["hasSummaryFocus"] is True, sidebar_before
        assert sidebar_before["hasQuickPin"] is True, sidebar_before
        assert sidebar_before["hasQuickFull"] is True, sidebar_before
        assert sidebar_before["hasQuickHop1"] is True, sidebar_before
        assert sidebar_before["hasQuickHop2"] is True, sidebar_before
        assert sidebar_before["quickPinDisabled"] is True, sidebar_before

        overlap_stats = await page.evaluate(
            """
            () => {
              if (typeof nodeLabelHitboxes === "undefined") return { labels: 0, overlapRatio: 0 };
              const boxes = Array.from(nodeLabelHitboxes.values());
              let overlaps = 0;
              let pairs = 0;
              for (let i = 0; i < boxes.length; i += 1) {
                const a = boxes[i];
                for (let j = i + 1; j < boxes.length; j += 1) {
                  const b = boxes[j];
                  pairs += 1;
                  const w = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x));
                  const h = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
                  if (w > 0 && h > 0) overlaps += 1;
                }
              }
              return {
                labels: boxes.length,
                overlapRatio: pairs > 0 ? overlaps / pairs : 0,
              };
            }
            """
        )
        assert overlap_stats["labels"] > 0, overlap_stats
        assert overlap_stats["overlapRatio"] < 0.18, overlap_stats

        edge_label_full_mode = await page.evaluate(
            """
            () => {
              let visibleEdges = 0;
              let visibleLabeledEdges = 0;
              for (const edgeId of graph.edges()) {
                const attrs = graph.getEdgeAttributes(edgeId);
                if (attrs.hidden) continue;
                visibleEdges += 1;
                if (attrs.show_label === true) visibleLabeledEdges += 1;
              }
              return { visibleEdges, visibleLabeledEdges };
            }
            """
        )
        assert edge_label_full_mode["visibleEdges"] >= edge_label_full_mode["visibleLabeledEdges"], edge_label_full_mode
        assert edge_label_full_mode["visibleLabeledEdges"] == 0, edge_label_full_mode

        selection = await page.evaluate(
            """
            () => {
              if (typeof nodeLabelHitboxes === "undefined" || typeof renderer === "undefined") {
                return null;
              }
              const ratio = renderer.getRenderParams().pixelRatio || window.devicePixelRatio || 1;
              for (const [nodeId, box] of nodeLabelHitboxes.entries()) {
                if (!graph.hasNode(nodeId)) continue;
                if (graph.getNodeAttribute(nodeId, "hidden")) continue;
                return {
                  x: (box.x + box.width / 2) / ratio,
                  y: (box.y + box.height / 2) / ratio,
                };
              }
              return null;
            }
            """
        )
        assert selection is not None

        graph_box = await page.locator("#graph").bounding_box()
        assert graph_box is not None
        click_x = max(5.0, min(float(selection["x"]), graph_box["width"] - 5.0))
        click_y = max(5.0, min(float(selection["y"]), graph_box["height"] - 5.0))
        await page.locator("#graph").click(position={"x": click_x, "y": click_y})
        await page.wait_for_timeout(250)

        first_selection_state = await page.evaluate(
            """
            () => ({
              focusModeMetric: window.__remora_layout_metrics?.focus_mode ?? null,
              hop1Active: document.querySelector('[data-focus-mode="hop1"]')?.classList.contains("active") === true,
              fullActive: document.querySelector('[data-focus-mode="full"]')?.classList.contains("active") === true,
              summaryFocus: String(document.getElementById("summary-focus-mode")?.textContent || "").trim(),
              quickPinDisabled: !!document.getElementById("quick-pin-toggle")?.disabled,
            })
            """
        )
        assert first_selection_state["focusModeMetric"] == "hop1", first_selection_state
        assert first_selection_state["hop1Active"] is True, first_selection_state
        assert first_selection_state["fullActive"] is False, first_selection_state
        assert first_selection_state["summaryFocus"] == "hop1", first_selection_state
        assert first_selection_state["quickPinDisabled"] is False, first_selection_state

        edge_label_focus_mode = await page.evaluate(
            """
            () => {
              let visibleEdges = 0;
              let visibleLabeledEdges = 0;
              for (const edgeId of graph.edges()) {
                const attrs = graph.getEdgeAttributes(edgeId);
                if (attrs.hidden) continue;
                visibleEdges += 1;
                if (attrs.show_label === true) visibleLabeledEdges += 1;
              }
              return { visibleEdges, visibleLabeledEdges };
            }
            """
        )
        assert edge_label_focus_mode["visibleEdges"] >= edge_label_focus_mode["visibleLabeledEdges"], edge_label_focus_mode

        await page.click("#quick-focus-full")
        await page.wait_for_timeout(200)
        restored = await page.evaluate(
            """
            () => ({
              focusModeMetric: window.__remora_layout_metrics?.focus_mode ?? null,
              fullActive: document.querySelector('[data-focus-mode="full"]')?.classList.contains("active") === true,
              summaryFocus: String(document.getElementById("summary-focus-mode")?.textContent || "").trim(),
              visibleCount: graph.nodes().filter((id) => !graph.getNodeAttribute(id, "hidden")).length,
            })
            """
        )
        assert restored["focusModeMetric"] == "full", restored
        assert restored["fullActive"] is True, restored
        assert restored["summaryFocus"] == "full", restored
        assert restored["visibleCount"] >= 1, restored


@pytest.mark.asyncio
@pytest.mark.acceptance
async def test_web_graph_sidebar_send_updates_events_and_timeline(
    tmp_path: Path,
    chromium_page,
) -> None:
    config_path = _write_graph_ui_project(tmp_path)
    port = _reserve_port()

    async with _running_runtime(
        project_root=tmp_path,
        config_path=config_path,
        port=port,
    ) as base_url:
        nodes = await _wait_for_nodes(base_url)
        function_node = next(
            (node for node in nodes if node.get("node_type") == "function"),
            nodes[0],
        )
        node_id = str(function_node.get("node_id", "")).strip()
        expected_name = str(function_node.get("name", "")).strip() or node_id.split("::")[-1]
        assert node_id

        page = chromium_page
        await page.goto(
            f"{base_url}/?node={quote(node_id, safe='')}",
            wait_until="domcontentloaded",
        )
        await expect(page.locator("#agent-header")).to_contain_text(
            expected_name,
            timeout=15000,
        )

        token = f"ui-message-{uuid.uuid4().hex[:8]}"
        await page.fill("#chat-input", token)
        await page.click("#send-chat")

        await expect(page.locator("#events")).to_contain_text("agent_message", timeout=15000)
        await expect(page.locator("#timeline-container")).to_contain_text(
            "agent_message",
            timeout=15000,
        )
        await expect(page.locator("#timeline-container")).to_contain_text(token, timeout=15000)

        await _wait_for_event(
            base_url,
            lambda event: (
                event.get("event_type") == "agent_message"
                and event.get("payload", {}).get("to_agent") == node_id
                and event.get("payload", {}).get("content") == token
            ),
        )


@pytest.mark.asyncio
@pytest.mark.acceptance
async def test_web_graph_sse_status_indicator_changes_on_error_and_recovery(
    tmp_path: Path,
    chromium_page,
) -> None:
    config_path = _write_graph_ui_project(tmp_path)
    port = _reserve_port()

    async with _running_runtime(
        project_root=tmp_path,
        config_path=config_path,
        port=port,
    ) as base_url:
        page = chromium_page
        await page.add_init_script(
            """
            (() => {
              const NativeEventSource = window.EventSource;
              window.__remora_event_sources = [];
              function WrappedEventSource(...args) {
                const es = new NativeEventSource(...args);
                window.__remora_event_sources.push(es);
                return es;
              }
              WrappedEventSource.prototype = NativeEventSource.prototype;
              WrappedEventSource.CONNECTING = NativeEventSource.CONNECTING;
              WrappedEventSource.OPEN = NativeEventSource.OPEN;
              WrappedEventSource.CLOSED = NativeEventSource.CLOSED;
              window.EventSource = WrappedEventSource;
            })();
            """
        )
        await page.goto(base_url, wait_until="domcontentloaded")
        await page.wait_for_selector("#connection-status.connected", timeout=15000)
        await page.wait_for_function(
            "() => window.__remora_event_sources && window.__remora_event_sources.length > 0"
        )

        errored = await page.evaluate(
            """
            () => {
              const es = window.__remora_event_sources?.[0];
              if (!es || typeof es.onerror !== "function") return false;
              es.onerror(new Event("error"));
              return true;
            }
            """
        )
        assert errored is True
        await page.wait_for_selector("#connection-status.disconnected", timeout=15000)

        reopened = await page.evaluate(
            """
            () => {
              const es = window.__remora_event_sources?.[0];
              if (!es || typeof es.onopen !== "function") return false;
              es.onopen(new Event("open"));
              return true;
            }
            """
        )
        assert reopened is True
        await page.wait_for_selector("#connection-status.connected", timeout=15000)
