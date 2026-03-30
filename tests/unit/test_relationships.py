"""Tests for cross-file relationship extraction."""

from __future__ import annotations

import pytest

from remora.code.languages import LanguageRegistry
from remora.code.relationships import (
    RawRelationship,
    extract_imports,
    extract_inheritance,
    resolve_relationships,
)
from remora.defaults import default_queries_dir


@pytest.fixture
def python_plugin():
    registry = LanguageRegistry.from_defaults()
    return registry.get_by_name("python")


@pytest.fixture
def query_paths():
    return [default_queries_dir()]


class TestExtractImports:
    def test_simple_import(self, python_plugin, query_paths):
        source = b"import os\n"
        rels = extract_imports(source, python_plugin, "app.py", "app.py::__file__", query_paths)
        assert any(r.target_name == "os" and r.edge_type == "imports" for r in rels)

    def test_from_import(self, python_plugin, query_paths):
        source = b"from os.path import join\n"
        rels = extract_imports(source, python_plugin, "app.py", "app.py::__file__", query_paths)
        assert any(
            r.target_name == "join" and r.target_module == "os.path" and r.edge_type == "imports"
            for r in rels
        )

    def test_from_import_dotted_target(self, python_plugin, query_paths):
        source = b"from remora.core.model.node import Node\n"
        rels = extract_imports(source, python_plugin, "app.py", "app.py::__file__", query_paths)
        assert any(
            r.target_name == "Node" and r.target_module == "remora.core.model.node"
            for r in rels
        )

    def test_multiple_imports(self, python_plugin, query_paths):
        source = b"import os\nimport sys\nfrom pathlib import Path\n"
        rels = extract_imports(source, python_plugin, "app.py", "app.py::__file__", query_paths)
        target_names = {r.target_name for r in rels}
        assert "os" in target_names
        assert "sys" in target_names
        assert "Path" in target_names

    def test_no_imports(self, python_plugin, query_paths):
        source = b"def hello():\n    pass\n"
        rels = extract_imports(source, python_plugin, "app.py", "app.py::__file__", query_paths)
        assert rels == []

    def test_deduplication(self, python_plugin, query_paths):
        source = b"from os import path\nfrom os import path\n"
        rels = extract_imports(source, python_plugin, "app.py", "app.py::__file__", query_paths)
        path_rels = [r for r in rels if r.target_name == "path"]
        assert len(path_rels) == 1


class TestExtractInheritance:
    def test_simple_inheritance(self, python_plugin, query_paths):
        source = b"class Dog(Animal):\n    pass\n"
        nodes_by_name = {"Dog": "app.py::Dog"}
        rels = extract_inheritance(source, python_plugin, "app.py", nodes_by_name, query_paths)
        assert len(rels) == 1
        assert rels[0].source_node_id == "app.py::Dog"
        assert rels[0].target_name == "Animal"
        assert rels[0].edge_type == "inherits"

    def test_multiple_bases(self, python_plugin, query_paths):
        source = b"class Dog(Animal, Trainable):\n    pass\n"
        nodes_by_name = {"Dog": "app.py::Dog"}
        rels = extract_inheritance(source, python_plugin, "app.py", nodes_by_name, query_paths)
        base_names = {r.target_name for r in rels}
        assert "Animal" in base_names
        assert "Trainable" in base_names

    def test_skips_builtin_bases(self, python_plugin, query_paths):
        source = b"class MyError(Exception):\n    pass\n"
        nodes_by_name = {"MyError": "app.py::MyError"}
        rels = extract_inheritance(source, python_plugin, "app.py", nodes_by_name, query_paths)
        assert rels == []

    def test_unknown_class_name_skipped(self, python_plugin, query_paths):
        source = b"class Dog(Animal):\n    pass\n"
        nodes_by_name = {}
        rels = extract_inheritance(source, python_plugin, "app.py", nodes_by_name, query_paths)
        assert rels == []

    def test_no_inheritance(self, python_plugin, query_paths):
        source = b"class Dog:\n    pass\n"
        nodes_by_name = {"Dog": "app.py::Dog"}
        rels = extract_inheritance(source, python_plugin, "app.py", nodes_by_name, query_paths)
        assert rels == []


class TestResolveRelationships:
    def test_resolve_import_with_qualified_name(self):
        raw = [
            RawRelationship(
                source_node_id="app.py::__file__",
                target_name="Node",
                edge_type="imports",
                target_module="remora.core.model.node",
            )
        ]
        name_index = {
            "remora.core.model.node.Node": ["src/remora/core/model/node.py::Node"],
            "Node": ["src/remora/core/model/node.py::Node", "other.py::Node"],
        }
        edges = resolve_relationships(raw, name_index)
        assert len(edges) == 1
        assert edges[0].to_id == "src/remora/core/model/node.py::Node"

    def test_resolve_import_fallback_to_bare_name(self):
        raw = [
            RawRelationship(
                source_node_id="app.py::__file__",
                target_name="Config",
                edge_type="imports",
                target_module="some.unknown.module",
            )
        ]
        name_index = {"Config": ["config.py::Config"]}
        edges = resolve_relationships(raw, name_index)
        assert len(edges) == 1
        assert edges[0].to_id == "config.py::Config"

    def test_resolve_inheritance(self):
        raw = [
            RawRelationship(
                source_node_id="app.py::Dog",
                target_name="Animal",
                edge_type="inherits",
            )
        ]
        name_index = {"Animal": ["animals.py::Animal"]}
        edges = resolve_relationships(raw, name_index)
        assert len(edges) == 1
        assert edges[0].from_id == "app.py::Dog"
        assert edges[0].to_id == "animals.py::Animal"
        assert edges[0].edge_type == "inherits"

    def test_unresolved_target_dropped(self):
        raw = [
            RawRelationship(
                source_node_id="app.py::Dog",
                target_name="UnknownBase",
                edge_type="inherits",
            )
        ]
        name_index = {}
        edges = resolve_relationships(raw, name_index)
        assert edges == []

    def test_self_edge_filtered(self):
        raw = [
            RawRelationship(
                source_node_id="app.py::Foo",
                target_name="Foo",
                edge_type="inherits",
            )
        ]
        name_index = {"Foo": ["app.py::Foo"]}
        edges = resolve_relationships(raw, name_index)
        assert edges == []

    def test_multiple_candidates(self):
        raw = [
            RawRelationship(
                source_node_id="app.py::Dog",
                target_name="Config",
                edge_type="inherits",
            )
        ]
        name_index = {"Config": ["a.py::Config", "b.py::Config"]}
        edges = resolve_relationships(raw, name_index)
        assert len(edges) == 2
        assert {e.to_id for e in edges} == {"a.py::Config", "b.py::Config"}
