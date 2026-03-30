from __future__ import annotations

from pathlib import Path

import hashlib
import pytest

from remora.code.discovery import discover
from remora.code.languages import LanguageRegistry
from remora.core.model.node import Node
from tests.factories import write_file


def test_discover_python_function(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    write_file(source, "def greet(name):\n    return f'hi {name}'\n")

    registry = LanguageRegistry.from_defaults()
    nodes = discover(
        [tmp_path],
        language_map={".py": "python"},
        language_registry=registry,
    )
    func = next(node for node in nodes if node.name == "greet")

    assert func.node_type == "function"
    assert func.start_line == 1
    assert func.end_line == 2
    assert func.source_hash == hashlib.sha256(func.text.encode("utf-8")).hexdigest()


def test_discover_python_class_and_method(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    write_file(source, "class Greeter:\n    def hello(self):\n        return 'ok'\n")

    registry = LanguageRegistry.from_defaults()
    nodes = discover([tmp_path], language_map={".py": "python"}, language_registry=registry)
    klass = next(node for node in nodes if node.name == "Greeter")
    method = next(node for node in nodes if node.name == "hello")

    assert klass.node_type == "class"
    assert method.node_type == "method"
    assert method.parent_id == klass.node_id
    assert method.full_name == "Greeter.hello"


def test_discover_python_decorated_and_async(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    write_file(
        source,
        "@decorator\ndef decorated():\n    return 1\n\nasync def async_fn():\n    return 2\n",
    )

    registry = LanguageRegistry.from_defaults()
    nodes = discover([tmp_path], language_map={".py": "python"}, language_registry=registry)
    names = {node.name for node in nodes}

    assert "decorated" in names
    assert "async_fn" in names


def test_discover_markdown_sections_hierarchy(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    write_file(readme, "# Top\n\n## Install\n\n### From Source\n")

    registry = LanguageRegistry.from_defaults()
    nodes = discover([tmp_path], language_map={".md": "markdown"}, language_registry=registry)
    names = {node.full_name for node in nodes}

    assert "Top" in names
    assert "Top.Install" in names
    assert "Top.Install.From Source" in names


def test_discover_toml_tables(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    write_file(pyproject, "[tool.ruff.lint]\nselect = ['E']\n\n[project]\nname = 'x'\n")

    registry = LanguageRegistry.from_defaults()
    nodes = discover([tmp_path], language_map={".toml": "toml"}, language_registry=registry)
    names = {node.full_name for node in nodes}
    assert "tool.ruff.lint" in names
    assert "project" in names


def test_discover_ignores_patterns(tmp_path: Path) -> None:
    ignored = tmp_path / "node_modules" / "ignore_me.py"
    kept = tmp_path / "src" / "keep_me.py"
    write_file(ignored, "def ignored():\n    return 1\n")
    write_file(kept, "def kept():\n    return 2\n")

    registry = LanguageRegistry.from_defaults()
    nodes = discover(
        [tmp_path],
        language_map={".py": "python"},
        language_registry=registry,
        ignore_patterns=("node_modules",),
    )
    names = {node.name for node in nodes}

    assert "ignored" not in names
    assert "kept" in names


def test_discover_query_override(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    write_file(source, "def only_function():\n    return 1\n\nclass C:\n    pass\n")

    override_dir = tmp_path / "queries"
    override_dir.mkdir(parents=True, exist_ok=True)
    write_file(
        override_dir / "python.scm",
        "(class_definition name: (identifier) @node.name) @node\n",
    )

    registry = LanguageRegistry.from_defaults()
    nodes = discover(
        [tmp_path],
        language_map={".py": "python"},
        language_registry=registry,
        query_paths=[override_dir],
    )
    names = {node.name for node in nodes}
    assert names == {"C"}


def test_discover_multiple_files(tmp_path: Path) -> None:
    write_file(tmp_path / "a.py", "def a():\n    return 1\n")
    write_file(tmp_path / "b.py", "def b():\n    return 2\n")

    registry = LanguageRegistry.from_defaults()
    nodes = discover([tmp_path], language_map={".py": "python"}, language_registry=registry)
    names = {node.name for node in nodes}

    assert {"a", "b"}.issubset(names)


def test_discover_empty_dir(tmp_path: Path) -> None:
    registry = LanguageRegistry.from_defaults()
    nodes = discover([tmp_path], language_map={".py": "python"}, language_registry=registry)
    assert nodes == []


def test_configured_language_not_in_registry_raises(tmp_path: Path) -> None:
    write_file(tmp_path / "x.foo", "hello")
    registry = LanguageRegistry.from_defaults()
    with pytest.raises(ValueError, match="unknown"):
        discover([tmp_path], language_map={".foo": "unknown"}, language_registry=registry)


def test_unconfigured_extension_is_skipped(tmp_path: Path) -> None:
    write_file(tmp_path / "x.foo", "hello")
    registry = LanguageRegistry.from_defaults()
    nodes = discover([tmp_path], language_map={".py": "python"}, language_registry=registry)
    assert nodes == []


def test_discover_with_fresh_language_registry_instances(tmp_path: Path) -> None:
    write_file(tmp_path / "example.py", "def greet(name):\n    return f'hi {name}'\n")
    first = discover(
        [tmp_path],
        language_map={".py": "python"},
        language_registry=LanguageRegistry.from_defaults(),
    )
    second = discover(
        [tmp_path],
        language_map={".py": "python"},
        language_registry=LanguageRegistry.from_defaults(),
    )
    assert len(first) == len(second) == 1
    assert first[0].name == "greet"
    assert second[0].name == "greet"


def test_discover_uses_injected_language_registry(tmp_path: Path) -> None:
    write_file(tmp_path / "example.py", "def greet(name):\n    return f'hi {name}'\n")
    registry = LanguageRegistry.from_defaults()
    nodes = discover([tmp_path], language_map={".py": "python"}, language_registry=registry)
    assert any(node.name == "greet" for node in nodes)


def test_discover_returns_mutable_node_model() -> None:
    node = Node(
        node_id="a::b",
        node_type="function",
        name="b",
        full_name="b",
        file_path="a.py",
        text="def b():\n    pass\n",
        source_hash=hashlib.sha256("def b():\n    pass\n".encode("utf-8")).hexdigest(),
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=17,
    )

    node.name = "changed"
    assert node.name == "changed"
