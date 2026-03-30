from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import tree_sitter_markdown

from remora.code.languages import GenericLanguagePlugin, LanguageRegistry, PythonPlugin
from remora.defaults import default_queries_dir


def make_ts_node(node_type: str, parent=None, children=None):  # noqa: ANN001, ANN202
    return SimpleNamespace(type=node_type, parent=parent, children=children or [])


def test_language_registry_resolves_by_name_and_extension() -> None:
    registry = LanguageRegistry.from_defaults()
    assert registry.get_by_name("python") is not None
    assert registry.get_by_extension(".py") is not None
    assert registry.get_by_extension(".md") is not None
    assert registry.get_by_extension(".toml") is not None


def test_python_plugin_resolve_node_type() -> None:
    plugin = PythonPlugin(default_queries_dir() / "python.scm")
    class_node = make_ts_node("class_definition")
    method_node = make_ts_node("function_definition", parent=class_node)
    fn_node = make_ts_node("function_definition")

    assert plugin.resolve_node_type(class_node) == "class"
    assert plugin.resolve_node_type(method_node) == "method"
    assert plugin.resolve_node_type(fn_node) == "function"


def test_generic_language_plugin_node_type_resolution() -> None:
    markdown = GenericLanguagePlugin(
        name="markdown",
        extensions=[".md"],
        query_path=default_queries_dir() / "markdown.scm",
        default_node_type="section",
    )
    toml = GenericLanguagePlugin(
        name="toml",
        extensions=[".toml"],
        query_path=default_queries_dir() / "toml.scm",
        default_node_type="table",
    )
    assert markdown.resolve_node_type(make_ts_node("heading")) == "section"
    assert toml.resolve_node_type(make_ts_node("table")) == "table"


def test_language_registry_supports_custom_language_from_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    query_file = tmp_path / "custom.scm"
    query_file.write_text("(heading) @node\n", encoding="utf-8")

    class _FakeModule:
        @staticmethod
        def language():  # noqa: ANN001
            return tree_sitter_markdown.language()

    monkeypatch.setattr(
        "remora.code.languages.importlib.import_module",
        lambda name: _FakeModule if name == "tree_sitter_custom" else None,
    )

    registry = LanguageRegistry.from_config(
        {
            "custom": {
                "extensions": [".custom"],
                "query_file": "custom.scm",
                "default_node_type": "heading",
            }
        },
        [tmp_path],
    )
    plugin = registry.get_by_extension(".custom")
    assert plugin is not None
    assert plugin.name == "custom"
    assert plugin.resolve_node_type(make_ts_node("anything")) == "heading"
    assert plugin.get_language() is not None


def test_missing_grammar_gives_clear_error(monkeypatch) -> None:
    plugin = GenericLanguagePlugin(
        name="fakeland",
        extensions=[".fake"],
        query_path=Path("/tmp/fakeland.scm"),
    )

    def raise_import_error(_name: str):  # noqa: ANN202
        raise ImportError("not installed")

    monkeypatch.setattr("remora.code.languages.importlib.import_module", raise_import_error)

    with pytest.raises(
        ImportError,
        match=r"Install with: pip install remora\[fakeland\]",
    ):
        plugin.get_language()
