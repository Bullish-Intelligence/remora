"""Code plugin package."""

from remora.code.directories import DirectoryManager
from remora.code.discovery import discover
from remora.code.languages import LanguageRegistry
from remora.code.paths import resolve_discovery_paths, resolve_query_paths, walk_source_files
from remora.code.reconciler import FileReconciler
from remora.code.virtual_agents import VirtualAgentManager
from remora.code.watcher import FileWatcher
from remora.core.model.node import Node

__all__ = [
    "Node",
    "discover",
    "DirectoryManager",
    "FileReconciler",
    "FileWatcher",
    "LanguageRegistry",
    "VirtualAgentManager",
    "resolve_discovery_paths",
    "resolve_query_paths",
    "walk_source_files",
]
