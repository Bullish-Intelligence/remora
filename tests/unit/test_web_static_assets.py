from __future__ import annotations

import tomllib
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from remora.core.events import EventBus, EventStore
from remora.core.storage.db import open_database
from remora.core.storage.graph import NodeStore
from remora.web.server import create_app

_ROOT = Path(__file__).resolve().parents[2]
_STATIC_DIR = _ROOT / "src" / "remora" / "web" / "static"
_PYPROJECT = _ROOT / "pyproject.toml"


@pytest_asyncio.fixture
async def static_client(tmp_path: Path):
    db = await open_database(tmp_path / "web-static-assets.db")
    event_bus = EventBus()
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db, event_bus=event_bus)
    await event_store.create_tables()
    app = create_app(event_store, node_store, event_bus)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    await db.close()


def test_vendored_javascript_files_exist() -> None:
    assert (_STATIC_DIR / "vendor" / "graphology.umd.min.js").is_file()
    assert (_STATIC_DIR / "vendor" / "sigma.min.js").is_file()
    assert (_STATIC_DIR / "main.js").is_file()
    assert (_STATIC_DIR / "graph-state.js").is_file()
    assert (_STATIC_DIR / "layout-engine.js").is_file()
    assert (_STATIC_DIR / "renderer.js").is_file()
    assert (_STATIC_DIR / "interactions.js").is_file()
    assert (_STATIC_DIR / "events.js").is_file()
    assert (_STATIC_DIR / "panels.js").is_file()


@pytest.mark.asyncio
async def test_vendored_javascript_files_are_served(static_client: httpx.AsyncClient) -> None:
    graphology = await static_client.get("/static/vendor/graphology.umd.min.js")
    sigma = await static_client.get("/static/vendor/sigma.min.js")
    main_js = await static_client.get("/static/main.js")

    assert graphology.status_code == 200
    assert sigma.status_code == 200
    assert main_js.status_code == 200
    assert "javascript" in graphology.headers["content-type"]
    assert "javascript" in sigma.headers["content-type"]
    assert "javascript" in main_js.headers["content-type"]
    assert "graphology" in graphology.text.lower()
    assert "sigma" in sigma.text.lower()
    assert "createGraphState" in main_js.text


def test_hatch_wheel_includes_static_assets() -> None:
    pyproject = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    wheel_target = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
    include = wheel_target["include"]
    assert "src/remora/web/static/**/*.js" in include
    assert "src/remora/web/static/**/*.html" in include
