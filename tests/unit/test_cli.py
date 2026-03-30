from __future__ import annotations

import io
import logging
import sys
import types
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from remora.__main__ import _configure_file_logging, _configure_logging, _index, _start, app
from remora.core.model.config import Config, ProjectConfig, SearchConfig, SearchMode


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Remora" in result.stdout
    assert "start" in result.stdout
    assert "lsp" in result.stdout


def test_cli_start_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["start", "--help"])
    assert result.exit_code == 0
    assert "--project-root" in result.stdout
    assert "--bind" in result.stdout
    assert "--no-web" in result.stdout


def test_cli_lsp_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["lsp", "--help"])
    assert result.exit_code == 0
    assert "--project-root" in result.stdout
    assert "--log-level" in result.stdout


def test_cli_lsp_requires_existing_db(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "lsp",
            "--project-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 1


def test_lsp_wrapper_error_message_uses_uv_sync(monkeypatch) -> None:
    import builtins

    import remora.lsp as lsp_module

    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        if name == "remora.lsp.server":
            raise ImportError("pygls missing")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError) as exc_info:
        lsp_module.create_lsp_server_standalone(Path("/tmp/remora.db"))
    message = str(exc_info.value)
    assert "uv sync --extra lsp" in message
    assert "docs/HOW_TO_USE_REMORA.md#lsp-setup" in message


def test_cli_lsp_reports_dependency_message_when_import_fails(
    tmp_path: Path, monkeypatch
) -> None:
    db_dir = tmp_path / ".remora"
    db_dir.mkdir(parents=True, exist_ok=True)
    (db_dir / "remora.db").write_text("", encoding="utf-8")

    fake_module = types.ModuleType("remora.lsp")

    def fail_create_lsp(_db_path: Path):  # noqa: ANN202
        raise ImportError(
            "LSP support requires pygls. Install with: uv sync --extra lsp\n"
            "See docs/HOW_TO_USE_REMORA.md#lsp-setup for full setup instructions."
        )

    fake_module.create_lsp_server_standalone = fail_create_lsp
    monkeypatch.setitem(sys.modules, "remora.lsp", fake_module)

    runner = CliRunner()
    result = runner.invoke(app, ["lsp", "--project-root", str(tmp_path)])
    assert result.exit_code == 1
    assert "uv sync --extra lsp" in result.output


def test_cli_start_smoke(tmp_path: Path) -> None:
    runner = CliRunner()
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("def a():\n    return 1\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "start",
            "--project-root",
            str(tmp_path),
            "--bind",
            "127.0.0.1",
            "--no-web",
            "--run-seconds",
            "0.1",
        ],
    )

    assert result.exit_code == 0
    assert (tmp_path / ".remora" / "remora.db").exists()
    log_path = tmp_path / ".remora" / "remora.log"
    assert log_path.exists()
    assert "Initializing runtime services" in log_path.read_text(encoding="utf-8")


def test_configure_logging_keeps_existing_root_handlers() -> None:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    marker = logging.StreamHandler(io.StringIO())
    root_logger.addHandler(marker)

    try:
        _configure_logging("INFO")
        assert marker in root_logger.handlers
        assert root_logger.level == logging.INFO
    finally:
        root_logger.setLevel(original_level)
        for handler in list(root_logger.handlers):
            if handler not in original_handlers:
                root_logger.removeHandler(handler)
                handler.close()


def test_configure_logging_lsp_mode_uses_stderr() -> None:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level

    try:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()

        _configure_logging("INFO", lsp_mode=True)
        stream_handlers = [
            handler
            for handler in root_logger.handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
        ]
        assert any(handler.stream is sys.stderr for handler in stream_handlers)
    finally:
        root_logger.setLevel(original_level)
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()
        for handler in original_handlers:
            root_logger.addHandler(handler)


def test_configure_file_logging_replaces_stale_file_handlers(tmp_path: Path) -> None:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    root_logger.setLevel(logging.INFO)

    try:
        # Start from a clean logger so this test is deterministic.
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)

        log_a = tmp_path / "a" / "remora.log"
        log_b = tmp_path / "b" / "remora.log"
        _configure_file_logging(log_a)
        file_handlers = [
            handler for handler in root_logger.handlers if isinstance(handler, logging.FileHandler)
        ]
        assert len(file_handlers) == 1
        first_handler = file_handlers[0]
        assert Path(first_handler.baseFilename).resolve() == log_a.resolve()

        _configure_file_logging(log_b)
        file_handlers = [
            handler for handler in root_logger.handlers if isinstance(handler, logging.FileHandler)
        ]
        assert len(file_handlers) == 1
        assert Path(file_handlers[0].baseFilename).resolve() == log_b.resolve()
        # The previous handler should be closed when it is replaced.
        assert first_handler.stream is None or first_handler.stream.closed
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            if handler not in original_handlers:
                handler.close()
        root_logger.setLevel(original_level)
        for handler in original_handlers:
            root_logger.addHandler(handler)


@pytest.mark.asyncio
async def test_start_calls_shutdown_when_lifecycle_start_fails(tmp_path: Path, monkeypatch) -> None:
    import remora.__main__ as main_module

    calls: list[str] = []

    class FakeLifecycle:
        def __init__(self, **_kwargs):  # noqa: ANN003, D401
            calls.append("init")

        async def start(self) -> None:
            calls.append("start")
            raise RuntimeError("boom")

        async def run(self, *, run_seconds: float = 0.0) -> None:
            del run_seconds
            calls.append("run")

        async def shutdown(self) -> None:
            calls.append("shutdown")

    monkeypatch.setattr(main_module, "RemoraLifecycle", FakeLifecycle)
    monkeypatch.setattr(main_module, "load_config", lambda _path: Config())

    with pytest.raises(RuntimeError, match="boom"):
        await _start(
            project_root=tmp_path,
            config_path=None,
            port=8080,
            no_web=True,
            bind="127.0.0.1",
            run_seconds=0.0,
            log_events=False,
            lsp=False,
        )

    assert calls == ["init", "start", "shutdown"]


@pytest.mark.asyncio
async def test_index_exits_when_search_disabled(tmp_path: Path) -> None:
    with pytest.raises(typer.Exit):
        await _index(
            project_root=tmp_path,
            config_path=None,
            collection=None,
            include=None,
            exclude=None,
        )


@pytest.mark.asyncio
async def test_index_happy_path_calls_index_directory_for_each_discovery_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import remora.__main__ as main_module

    class FakeService:
        last_instance = None

        def __init__(self, config, project_root):  # noqa: ANN001, ANN204
            self.available = True
            self.calls: list[tuple[str, str | None, list[str] | None, list[str] | None]] = []
            self.closed = False
            type(self).last_instance = self

        async def initialize(self) -> None:
            return None

        async def index_directory(
            self,
            path: str,
            collection: str | None = None,
            include: list[str] | None = None,
            exclude: list[str] | None = None,
        ) -> dict:
            self.calls.append((path, collection, include, exclude))
            return {"files_processed": 1, "chunks_created": 2, "errors": []}

        async def close(self) -> None:
            self.closed = True

    path_a = tmp_path / "src"
    path_b = tmp_path / "docs"
    path_a.mkdir(parents=True)
    path_b.mkdir(parents=True)

    config = Config(
        search=SearchConfig(enabled=True, mode=SearchMode.REMOTE),
        project=ProjectConfig(discovery_paths=("src", "docs")),
    )

    monkeypatch.setattr(main_module, "load_config", lambda _path: config)
    monkeypatch.setattr(
        main_module, "resolve_discovery_paths", lambda *_args, **_kwargs: [path_a, path_b]
    )
    monkeypatch.setattr("remora.core.services.search.SearchService", FakeService)

    await _index(
        project_root=tmp_path,
        config_path=None,
        collection="code",
        include=["*.py"],
        exclude=["*.tmp"],
    )

    service = FakeService.last_instance
    assert service is not None
    assert service.calls == [
        (str(path_a), "code", ["*.py"], ["*.tmp"]),
        (str(path_b), "code", ["*.py"], ["*.tmp"]),
    ]
    assert service.closed is True
