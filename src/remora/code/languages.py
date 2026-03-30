"""Language plugin system for tree-sitter based discovery."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Protocol

from tree_sitter import Language, Query


class LanguagePlugin(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def extensions(self) -> list[str]: ...

    def get_language(self) -> Language: ...

    def get_default_query_path(self) -> Path: ...

    def get_query(self, query_paths: list[Path]) -> Query: ...

    def resolve_node_type(self, ts_node: Any) -> str: ...


class PythonPlugin:
    """Language plugin for Python with class/method ancestry handling."""

    def __init__(self, query_path: Path, extensions: list[str] | None = None) -> None:
        self._query_path = query_path
        self._extensions = list(extensions or [".py"])
        self._module_name = "tree_sitter_python"
        self._package_name = "tree-sitter-python"
        self._language: Language | None = None
        self._query: Query | None = None
        self._query_paths: list[Path] | None = None

    @property
    def name(self) -> str:
        return "python"

    @property
    def extensions(self) -> list[str]:
        return self._extensions

    def get_language(self) -> Language:
        if self._language is None:
            mod = _load_language_module(
                language_name=self.name,
                module_name=self._module_name,
                package_name=self._package_name,
            )
            self._language = Language(mod.language())
        return self._language

    def get_default_query_path(self) -> Path:
        return self._query_path

    def get_query(self, query_paths: list[Path]) -> Query:
        if self._query is None or self._query_paths != query_paths:
            query_file = self._resolve_query_file(query_paths)
            query_text = query_file.read_text(encoding="utf-8")
            self._query = Query(self.get_language(), query_text)
            self._query_paths = query_paths
        return self._query

    def _resolve_query_file(self, query_paths: list[Path]) -> Path:
        for query_dir in query_paths:
            candidate = query_dir / f"{self.name}.scm"
            if candidate.exists():
                return candidate
        return self._query_path

    def resolve_node_type(self, ts_node: Any) -> str:
        if ts_node.type == "class_definition":
            return "class"
        if ts_node.type == "function_definition":
            return "method" if self._has_class_ancestor(ts_node) else "function"
        if ts_node.type == "decorated_definition":
            target = self._decorated_target(ts_node)
            if target and target.type == "class_definition":
                return "class"
            if target and target.type == "function_definition":
                return "method" if self._has_class_ancestor(ts_node) else "function"
        return "function"

    @staticmethod
    def _has_class_ancestor(node: Any) -> bool:
        current = node.parent
        while current is not None:
            if current.type == "class_definition":
                return True
            if current.type == "decorated_definition":
                for child in current.children:
                    if child.type == "class_definition":
                        return True
            current = current.parent
        return False

    @staticmethod
    def _decorated_target(node: Any) -> Any | None:
        for child in node.children:
            if child.type in {"function_definition", "class_definition"}:
                return child
        return None


class GenericLanguagePlugin:
    """Config-driven language plugin for simple languages."""

    def __init__(
        self,
        name: str,
        extensions: list[str],
        query_path: Path,
        node_type_rules: dict[str, str] | None = None,
        default_node_type: str = "function",
    ) -> None:
        self._name = name
        self._extensions = extensions
        self._query_path = query_path
        self._module_name = f"tree_sitter_{name}"
        self._package_name = f"tree-sitter-{name}"
        self._node_type_rules = node_type_rules or {}
        self._default_node_type = default_node_type
        self._language: Language | None = None
        self._query: Query | None = None
        self._query_paths: list[Path] | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def extensions(self) -> list[str]:
        return self._extensions

    def get_language(self) -> Language:
        if self._language is None:
            mod = _load_language_module(
                language_name=self.name,
                module_name=self._module_name,
                package_name=self._package_name,
            )
            self._language = Language(mod.language())
        return self._language

    def get_default_query_path(self) -> Path:
        return self._query_path

    def get_query(self, query_paths: list[Path]) -> Query:
        if self._query is None or self._query_paths != query_paths:
            query_file = self._resolve_query_file(query_paths)
            query_text = query_file.read_text(encoding="utf-8")
            self._query = Query(self.get_language(), query_text)
            self._query_paths = query_paths
        return self._query

    def _resolve_query_file(self, query_paths: list[Path]) -> Path:
        for query_dir in query_paths:
            candidate = query_dir / f"{self._name}.scm"
            if candidate.exists():
                return candidate
        return self._query_path

    def resolve_node_type(self, ts_node: Any) -> str:
        return self._node_type_rules.get(ts_node.type, self._default_node_type)


ADVANCED_PLUGINS: dict[str, type[PythonPlugin]] = {
    "python": PythonPlugin,
}


class LanguageRegistry:
    """Registry of language plugins, resolved by name or extension."""

    def __init__(self, plugins: list[LanguagePlugin] | None = None):
        self._by_name: dict[str, LanguagePlugin] = {}
        self._by_ext: dict[str, LanguagePlugin] = {}
        if plugins is not None:
            for plugin in plugins:
                self.register(plugin)

    def register(self, plugin: LanguagePlugin) -> None:
        self._by_name[plugin.name.lower()] = plugin
        for ext in plugin.extensions:
            self._by_ext[ext.lower()] = plugin

    def get_by_name(self, name: str) -> LanguagePlugin | None:
        return self._by_name.get(name.lower())

    def get_by_extension(self, ext: str) -> LanguagePlugin | None:
        return self._by_ext.get(ext.lower())

    @property
    def names(self) -> list[str]:
        return list(self._by_name.keys())

    @classmethod
    def from_config(
        cls,
        language_defs: dict[str, dict[str, Any]],
        query_search_paths: list[Path],
    ) -> LanguageRegistry:
        """Build a registry from YAML language definitions."""
        registry = cls(plugins=[])
        for lang_name, lang_config in language_defs.items():
            query_file = lang_config.get("query_file", f"{lang_name}.scm")
            query_path = _resolve_query_file(query_file, query_search_paths)
            extensions = list(lang_config.get("extensions", []))

            if lang_name in ADVANCED_PLUGINS:
                plugin = ADVANCED_PLUGINS[lang_name](
                    query_path=query_path,
                    extensions=extensions,
                )
            else:
                plugin = GenericLanguagePlugin(
                    name=lang_name,
                    extensions=extensions,
                    query_path=query_path,
                    node_type_rules=lang_config.get("node_type_rules"),
                    default_node_type=lang_config.get("default_node_type", "function"),
                )
            registry.register(plugin)
        return registry

    @classmethod
    def from_defaults(cls) -> LanguageRegistry:
        """Build a registry from shipped defaults.yaml language definitions."""
        from remora.defaults import default_queries_dir, load_defaults

        loaded = load_defaults()
        language_defs = loaded.get("languages", {}) if isinstance(loaded, dict) else {}
        if not isinstance(language_defs, dict):
            language_defs = {}
        return cls.from_config(language_defs, [default_queries_dir()])


def _resolve_query_file(filename: str, search_paths: list[Path]) -> Path:
    """Find a query file in the search paths."""
    for search_dir in search_paths:
        candidate = search_dir / filename
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Query file {filename} not found in {search_paths}")


def _load_language_module(*, language_name: str, module_name: str, package_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ImportError:
        raise ImportError(
            f"Language '{language_name}' requires {package_name}. "
            f"Install with: pip install remora[{language_name}]"
        ) from None


__all__ = [
    "LanguagePlugin",
    "GenericLanguagePlugin",
    "PythonPlugin",
    "ADVANCED_PLUGINS",
    "LanguageRegistry",
]
