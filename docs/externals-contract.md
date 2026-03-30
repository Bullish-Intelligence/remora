# Externals Contract

This document defines the versioned core-to-bundle externals API contract.

- Current core externals version: `2`
- Source of truth: `src/remora/core/tools/context.py`
- Bundle declaration field: `externals_version` in `bundle.yaml`

## Compatibility rule

When loading `_bundle/bundle.yaml`:

1. If `externals_version` is omitted, no version constraint is enforced.
2. If `externals_version` is greater than core `EXTERNALS_VERSION`, the turn fails with `IncompatibleBundleError`.

## Version 2 capabilities

### File capabilities

1. `read_file(path: str) -> str`
2. `write_file(path: str, content: str) -> None`
3. `list_dir(path: str = ".") -> list[str]`
4. `file_exists(path: str) -> bool`
5. `search_files(pattern: str) -> list[str]`
6. `search_content(pattern: str, path: str = ".") -> list[dict[str, Any]]`

### KV capabilities

1. `kv_get(key: str) -> Any | None`
2. `kv_set(key: str, value: Any) -> None`
3. `kv_delete(key: str) -> None`
4. `kv_list(prefix: str = "") -> list[str]`

### Graph capabilities

1. `graph_get_node(target_id: str) -> dict[str, Any]`
2. `graph_query_nodes(node_type: str | None = None, status: str | None = None, file_path: str | None = None) -> list[dict[str, Any]]`
3. `graph_get_edges(target_id: str) -> list[dict[str, Any]]`
4. `graph_get_children(parent_id: str | None = None) -> list[dict[str, Any]]`
5. `graph_set_status(target_id: str, new_status: str) -> bool`

### Event capabilities

1. `event_emit(event_type: str, payload: dict[str, Any], tags: list[str] | None = None) -> None`
2. `event_subscribe(event_types: list[str] | None = None, from_agents: list[str] | None = None, path_glob: str | None = None, tags: list[str] | None = None) -> int`
3. `event_unsubscribe(subscription_id: int) -> bool`
4. `event_get_history(target_id: str, limit: int = 20) -> list[dict[str, Any]]`

### Communication capabilities

1. `send_message(to_node_id: str, content: str) -> dict[str, str | bool]`
2. `broadcast(pattern: str, content: str) -> str`
3. `request_human_input(question: str, options: list[str] | None = None) -> str`
4. `propose_changes(reason: str = "") -> str`

### Search capabilities

1. `semantic_search(query: str, collection: str | None = None, top_k: int = 10, mode: str = "hybrid") -> list[dict[str, Any]]`
2. `find_similar_code(chunk_id: str, collection: str | None = None, top_k: int = 10) -> list[dict[str, Any]]`

### Identity capabilities

1. `get_node_source(node_id: str) -> str`
2. `my_node_id() -> str`
3. `my_correlation_id() -> str | None`
