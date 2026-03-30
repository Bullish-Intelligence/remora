from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.model.config import Config
from remora.core.storage.workspace import CairnWorkspaceService


class _FakeRawWorkspace:
    def __init__(self, path: str):
        self.path = path
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


@pytest.mark.asyncio
async def test_workspace_service_evicts_lru_and_closes_raw_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: dict[str, _FakeRawWorkspace] = {}
    open_calls = 0

    async def _fake_open_workspace(path: str):  # noqa: ANN202
        nonlocal open_calls
        open_calls += 1
        raw = _FakeRawWorkspace(path)
        opened[path] = raw
        return raw

    monkeypatch.setattr(
        "remora.core.storage.workspace.cairn_wm.open_workspace",
        _fake_open_workspace,
    )
    monkeypatch.setattr(CairnWorkspaceService, "_MAX_OPEN_WORKSPACES", 2)

    service = CairnWorkspaceService(Config(), tmp_path)
    await service.initialize()

    first = await service.get_agent_workspace("node-a")
    second = await service.get_agent_workspace("node-b")
    again_first = await service.get_agent_workspace("node-a")
    third = await service.get_agent_workspace("node-c")

    assert first is again_first
    assert first is not second
    assert third is not second
    assert open_calls == 3

    assert list(service._agent_workspaces.keys()) == ["node-a", "node-c"]
    assert "node-b" not in service._raw_agent_workspaces

    evicted_path = str(tmp_path / ".remora" / "agents" / service._safe_id("node-b"))
    assert opened[evicted_path].close_calls == 1

    await service.close()
