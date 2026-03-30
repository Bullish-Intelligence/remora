from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import httpx
import pytest
from tests.factories import write_file

from remora.core.model.config import BehaviorConfig, Config, InfraConfig, ProjectConfig
from remora.core.services.lifecycle import RemoraLifecycle


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _wait_for_health(client: httpx.AsyncClient, timeout_s: float = 5.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        try:
            response = await client.get("/api/health")
            if response.status_code == 200:
                return response.json()
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.05)
    raise AssertionError("health endpoint did not become ready within timeout")


async def _wait_for_semantic_edges(client: httpx.AsyncClient, timeout_s: float = 5.0) -> list[dict]:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get("/api/edges")
        if response.status_code == 200:
            semantic_edges = [
                edge
                for edge in response.json()
                if edge.get("edge_type") in {"imports", "inherits"}
            ]
            if semantic_edges:
                return semantic_edges
        await asyncio.sleep(0.05)
    raise AssertionError("semantic edges were not observed via /api/edges within timeout")


@pytest.mark.asyncio
async def test_lifecycle_discovers_nodes_serves_health_and_shuts_down(tmp_path: Path) -> None:
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")
    port = _free_port()
    config = Config(
        project=ProjectConfig(
            discovery_paths=("src",),
            discovery_languages=("python",),
        ),
        behavior=BehaviorConfig(
            language_map={".py": "python"},
            languages={"python": {"extensions": [".py"]}},
            query_search_paths=("@default",),
        ),
        infra=InfraConfig(workspace_root=".remora-lifecycle-test"),
    )
    lifecycle = RemoraLifecycle(
        config=config,
        project_root=tmp_path,
        bind="127.0.0.1",
        port=port,
        no_web=False,
        log_events=False,
        lsp=False,
        configure_file_logging=lambda _path: None,
    )

    try:
        await lifecycle.start()
        services = lifecycle._services  # noqa: SLF001
        assert services is not None

        nodes = await services.node_store.list_nodes()
        assert nodes
        assert any(node.node_id.endswith("::a") for node in nodes)

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=0.5) as client:
            health = await _wait_for_health(client)
            assert health.get("status") == "ok"

        await lifecycle.run(run_seconds=2.0)
    finally:
        await lifecycle.shutdown()

    leaked_remora_tasks = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and not task.done()
        and task.get_name().startswith("remora-")
    ]
    assert leaked_remora_tasks == []


@pytest.mark.asyncio
async def test_lifecycle_startup_exposes_semantic_edges_via_api(tmp_path: Path) -> None:
    write_file(tmp_path / "src" / "a.py", "from b import B\n\nclass A(B):\n    pass\n")
    write_file(tmp_path / "src" / "b.py", "class B:\n    pass\n")
    port = _free_port()
    config = Config(
        project=ProjectConfig(
            discovery_paths=("src",),
            discovery_languages=("python",),
        ),
        behavior=BehaviorConfig(
            language_map={".py": "python"},
            languages={"python": {"extensions": [".py"]}},
            query_search_paths=("@default",),
        ),
        infra=InfraConfig(workspace_root=".remora-lifecycle-test"),
    )
    lifecycle = RemoraLifecycle(
        config=config,
        project_root=tmp_path,
        bind="127.0.0.1",
        port=port,
        no_web=False,
        log_events=False,
        lsp=False,
        configure_file_logging=lambda _path: None,
    )

    try:
        await lifecycle.start()
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=0.5) as client:
            health = await _wait_for_health(client)
            assert health.get("status") == "ok"

            semantic_edges = await _wait_for_semantic_edges(client)
            assert any(
                edge["edge_type"] == "imports"
                and "a.py::A" in edge["from_id"]
                and "b.py::B" in edge["to_id"]
                for edge in semantic_edges
            )
            assert any(
                edge["edge_type"] == "inherits"
                and "a.py::A" in edge["from_id"]
                and "b.py::B" in edge["to_id"]
                for edge in semantic_edges
            )
    finally:
        await lifecycle.shutdown()
