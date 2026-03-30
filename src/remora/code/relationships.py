"""Cross-file relationship extraction from tree-sitter AST."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tree_sitter import Parser, Query, QueryCursor

from remora.code.languages import LanguagePlugin

logger = logging.getLogger(__name__)


@dataclass
class RawRelationship:
    """An unresolved relationship between source elements."""

    source_node_id: str
    target_name: str
    edge_type: str
    target_module: str | None = None


@dataclass
class ResolvedEdge:
    """A resolved edge ready for storage."""

    from_id: str
    to_id: str
    edge_type: str


def _load_query(
    plugin: LanguagePlugin,
    query_filename: str,
    query_paths: list[Path],
) -> Query | None:
    """Load a tree-sitter query file by name from query search paths."""
    for query_dir in query_paths:
        candidate = query_dir / query_filename
        if candidate.exists():
            query_text = candidate.read_text(encoding="utf-8")
            return Query(plugin.get_language(), query_text)

    default_dir = plugin.get_default_query_path().parent
    candidate = default_dir / query_filename
    if candidate.exists():
        query_text = candidate.read_text(encoding="utf-8")
        return Query(plugin.get_language(), query_text)

    return None


def _node_text(source: bytes, node: Any) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def extract_imports(
    source_bytes: bytes,
    plugin: LanguagePlugin,
    file_path: str,
    file_node_id: str,
    query_paths: list[Path],
) -> list[RawRelationship]:
    """Extract import relationships from a Python source file."""
    del file_path
    query = _load_query(plugin, "python_imports.scm", query_paths)
    if query is None:
        return []

    parser = Parser(plugin.get_language())
    tree = parser.parse(source_bytes)
    matches = QueryCursor(query).matches(tree.root_node)

    relationships: list[RawRelationship] = []
    seen: set[tuple[str, str]] = set()

    for _pattern_index, captures in matches:
        source_nodes = captures.get("import.source", [])
        target_nodes = captures.get("import.target", [])
        if not target_nodes:
            continue

        target_name = _node_text(source_bytes, target_nodes[0]).strip()
        source_module = (
            _node_text(source_bytes, source_nodes[0]).strip() if source_nodes else None
        )
        if not target_name:
            continue

        dedup_key = (source_module or "", target_name)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        relationships.append(
            RawRelationship(
                source_node_id=file_node_id,
                target_name=target_name,
                edge_type="imports",
                target_module=source_module,
            )
        )

    return relationships


def extract_inheritance(
    source_bytes: bytes,
    plugin: LanguagePlugin,
    file_path: str,
    nodes_by_name: dict[str, str],
    query_paths: list[Path],
) -> list[RawRelationship]:
    """Extract class inheritance relationships from a Python source file."""
    del file_path
    query = _load_query(plugin, "python_inheritance.scm", query_paths)
    if query is None:
        return []

    parser = Parser(plugin.get_language())
    tree = parser.parse(source_bytes)
    matches = QueryCursor(query).matches(tree.root_node)

    relationships: list[RawRelationship] = []

    for _pattern_index, captures in matches:
        class_name_nodes = captures.get("class.name", [])
        base_name_nodes = captures.get("class.base", [])
        if not class_name_nodes or not base_name_nodes:
            continue

        class_name = _node_text(source_bytes, class_name_nodes[0]).strip()
        base_name = _node_text(source_bytes, base_name_nodes[0]).strip()
        if not class_name or not base_name:
            continue
        if base_name in {"object", "type", "Exception", "BaseException"}:
            continue

        source_node_id = nodes_by_name.get(class_name)
        if source_node_id is None:
            continue

        relationships.append(
            RawRelationship(
                source_node_id=source_node_id,
                target_name=base_name,
                edge_type="inherits",
            )
        )

    return relationships


def resolve_relationships(
    raw: list[RawRelationship],
    name_index: dict[str, list[str]],
) -> list[ResolvedEdge]:
    """Resolve raw relationship targets to node IDs using the name index."""
    resolved: list[ResolvedEdge] = []

    for rel in raw:
        target_ids: list[str] = []
        if rel.edge_type == "imports" and rel.target_module:
            qualified = f"{rel.target_module}.{rel.target_name}"
            target_ids = name_index.get(qualified, [])
            if not target_ids:
                target_ids = name_index.get(rel.target_module, [])
            if not target_ids:
                target_ids = name_index.get(rel.target_name, [])
        else:
            target_ids = name_index.get(rel.target_name, [])

        target_ids = [tid for tid in target_ids if tid != rel.source_node_id]
        if not target_ids:
            logger.debug(
                "Unresolved %s: %s -> %s (module=%s)",
                rel.edge_type,
                rel.source_node_id,
                rel.target_name,
                rel.target_module,
            )
            continue

        for target_id in target_ids:
            resolved.append(
                ResolvedEdge(
                    from_id=rel.source_node_id,
                    to_id=target_id,
                    edge_type=rel.edge_type,
                )
            )

    return resolved


__all__ = [
    "RawRelationship",
    "ResolvedEdge",
    "extract_imports",
    "extract_inheritance",
    "resolve_relationships",
]
