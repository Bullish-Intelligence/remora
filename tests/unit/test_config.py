from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from remora.core.model.config import (
    BehaviorConfig,
    BundleConfig,
    Config,
    ProjectConfig,
    SearchConfig,
    SearchMode,
    _find_config_file,
    expand_env_vars,
    load_config,
)
from remora.core.utils import deep_merge


def test_default_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("REMORA_MAX_TURNS", raising=False)
    monkeypatch.delenv("REMORA_MODEL_DEFAULT", raising=False)
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.behavior.max_turns == 8
    assert config.behavior.bundle_overlays["function"] == "code-agent"
    assert config.behavior.bundle_overlays["directory"] == "directory-agent"
    assert "file" not in config.behavior.bundle_overlays
    assert config.behavior.language_map[".py"] == "python"
    assert "queries/" in config.behavior.query_search_paths
    assert config.runtime.actor_idle_timeout_s == 300.0


def test_legacy_bundle_mapping_key_rejected() -> None:
    """Old 'bundle_mapping' key is no longer silently migrated."""
    with pytest.raises(ValidationError):
        Config(bundle_mapping={"function": "special-agent"})


def test_load_from_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "remora.yaml"
    yaml_path.write_text(
        "max_turns: 20\n"
        "model_default: gpt-4\n"
        "language_map:\n"
        "  .py: python\n"
        "  .md: markdown\n"
        "query_search_paths:\n"
        "  - custom-queries/\n",
        encoding="utf-8",
    )
    config = load_config(yaml_path)
    assert config.behavior.max_turns == 20
    assert config.behavior.model_default == "gpt-4"
    assert config.behavior.language_map[".md"] == "markdown"
    assert config.behavior.query_search_paths == ("custom-queries/",)


def test_load_virtual_agents_from_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "remora.yaml"
    yaml_path.write_text(
        "virtual_agents:\n"
        "  - id: test-agent\n"
        "    role: test-agent\n"
        "    subscriptions:\n"
        "      - event_types: [node_changed]\n"
        "        path_glob: src/**\n"
        "        tags: [scaffold, ci]\n",
        encoding="utf-8",
    )
    config = load_config(yaml_path)
    assert len(config.virtual_agents) == 1
    assert config.virtual_agents[0].id == "test-agent"
    assert config.virtual_agents[0].role == "test-agent"
    assert config.virtual_agents[0].subscriptions[0].event_types == ("node_changed",)
    assert config.virtual_agents[0].subscriptions[0].tags == ("scaffold", "ci")


def test_env_var_expansion(monkeypatch) -> None:
    monkeypatch.setenv("TEST_MODEL", "gpt-5")
    data = {
        "model_default": "${TEST_MODEL:-fallback}",
        "model_api_key": "${MISSING_KEY:-default-key}",
        "nested": ["${MISSING_2:-x}", {"v": "${TEST_MODEL:-y}"}],
    }
    expanded = expand_env_vars(data)
    assert expanded["model_default"] == "gpt-5"
    assert expanded["model_api_key"] == "default-key"
    assert expanded["nested"] == ["x", {"v": "gpt-5"}]


def test_find_config_file(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    config_path = root / "remora.yaml"
    config_path.write_text("max_turns: 11", encoding="utf-8")

    monkeypatch.chdir(nested)
    found = _find_config_file()
    assert found == config_path


def test_invalid_language_map_rejected() -> None:
    with pytest.raises(ValidationError):
        Config(behavior=BehaviorConfig(language_map={"py": "python"}))


def test_empty_discovery_paths_rejected() -> None:
    with pytest.raises(ValidationError):
        Config(project=ProjectConfig(discovery_paths=()))


def test_bundle_rules_override_type_overlays() -> None:
    config = Config(
        behavior=BehaviorConfig(
            bundle_overlays={"function": "code-agent"},
            bundle_rules=(
                {
                    "node_type": "function",
                    "name_pattern": "test_*",
                    "bundle": "test-agent",
                },
            ),
        ),
    )
    assert config.resolve_bundle("function", "test_alpha") == "test-agent"
    assert config.resolve_bundle("function", "alpha") == "code-agent"


def test_search_config_defaults() -> None:
    search = SearchConfig()
    assert search.enabled is False
    assert search.mode == SearchMode.REMOTE
    assert search.embeddy_url == "http://localhost:8585"
    assert search.timeout == 30.0
    assert search.default_collection == "code"
    assert search.collection_map[".py"] == "code"
    assert search.db_path == ".remora/embeddy.db"
    assert search.model_name == "Qwen/Qwen3-VL-Embedding-2B"
    assert search.embedding_dimension == 2048


def test_search_config_invalid_mode_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchConfig(mode="invalid")


def test_bundle_config_rejects_unknown_prompt_keys() -> None:
    with pytest.raises(ValidationError, match="Unknown prompt keys"):
        BundleConfig(prompts={"chat": "ok", "analysis": "nope"})


def test_config_parses_search_dict() -> None:
    config = Config(
        search={
            "enabled": True,
            "mode": "remote",
            "embeddy_url": "http://localhost:8585",
            "timeout": 45.0,
            "default_collection": "code",
            "collection_map": {".py": "python-code", ".md": "docs"},
        }
    )
    assert config.search.enabled is True
    assert config.search.mode == SearchMode.REMOTE
    assert config.search.timeout == 45.0
    assert config.search.collection_map[".py"] == "python-code"


def test_load_from_yaml_with_search_section(tmp_path: Path) -> None:
    yaml_path = tmp_path / "remora.yaml"
    yaml_path.write_text(
        "search:\n"
        "  enabled: true\n"
        "  mode: remote\n"
        "  embeddy_url: http://localhost:9595\n"
        "  timeout: 60.0\n"
        "  default_collection: code\n"
        "  collection_map:\n"
        "    .py: code\n"
        "    .md: docs\n",
        encoding="utf-8",
    )
    config = load_config(yaml_path)
    assert config.search.enabled is True
    assert config.search.mode == SearchMode.REMOTE
    assert config.search.embeddy_url == "http://localhost:9595"
    assert config.search.timeout == 60.0
    assert config.search.collection_map[".md"] == "docs"


def test_deep_merge_basic() -> None:
    base = {"a": 1, "b": {"x": 10, "y": 20}}
    overlay = {"b": {"x": 99}, "c": 3}
    result = deep_merge(base, overlay)
    assert result == {"a": 1, "b": {"x": 99, "y": 20}, "c": 3}


def test_deep_merge_overlay_replaces_non_dict() -> None:
    base = {"a": [1, 2], "b": "text"}
    overlay = {"a": [3, 4]}
    result = deep_merge(base, overlay)
    assert result == {"a": [3, 4], "b": "text"}


def test_load_config_deep_merges_languages(tmp_path: Path) -> None:
    """User overriding one language should not destroy other default languages."""
    user_config = tmp_path / "remora.yaml"
    user_config.write_text(
        "languages:\n  python:\n    extensions: ['.py', '.pyi']\n",
        encoding="utf-8",
    )
    config = load_config(user_config)
    assert ".pyi" in config.behavior.languages["python"]["extensions"]
    assert "markdown" in config.behavior.languages
    assert "toml" in config.behavior.languages


def test_load_config_deep_merges_language_map(tmp_path: Path) -> None:
    """User adding a language_map entry should not destroy defaults."""
    user_config = tmp_path / "remora.yaml"
    user_config.write_text(
        "language_map:\n  '.rs': rust\n",
        encoding="utf-8",
    )
    config = load_config(user_config)
    assert config.behavior.language_map[".rs"] == "rust"
    assert config.behavior.language_map[".py"] == "python"


def test_runtime_config_actor_inbox_defaults() -> None:
    """Default values for actor inbox configuration."""
    from remora.core.model.config import OverflowPolicy, RuntimeConfig

    config = RuntimeConfig()
    assert config.actor_inbox_max_items == 1000
    assert config.actor_inbox_overflow_policy == OverflowPolicy.DROP_NEW
    assert config.max_reactive_turns_per_correlation == 3
    assert config.max_model_retries == 1


def test_runtime_config_invalid_overflow_policy_rejected() -> None:
    """Invalid overflow policy values should be rejected."""
    from remora.core.model.config import RuntimeConfig

    # Pydantic v2 validates enum by string value - invalid value raises ValidationError
    with pytest.raises(ValidationError):
        RuntimeConfig(actor_inbox_overflow_policy="invalid_policy")  # type: ignore[arg-type]


def test_runtime_config_invalid_inbox_size_rejected() -> None:
    """Invalid inbox sizes should be rejected."""
    from remora.core.model.config import RuntimeConfig

    with pytest.raises(ValidationError):
        RuntimeConfig(actor_inbox_max_items=0)

    with pytest.raises(ValidationError):
        RuntimeConfig(actor_inbox_max_items=-1)


def test_runtime_config_api_limit_defaults() -> None:
    """Default values for chat/conversation API bounds."""
    from remora.core.model.config import RuntimeConfig

    config = RuntimeConfig()
    assert config.chat_message_max_chars == 4000
    assert config.conversation_history_max_entries == 200
    assert config.conversation_message_max_chars == 2000


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("chat_message_max_chars", 0),
        ("chat_message_max_chars", -1),
        ("conversation_history_max_entries", 0),
        ("conversation_history_max_entries", -5),
        ("conversation_message_max_chars", 0),
        ("conversation_message_max_chars", -10),
        ("max_reactive_turns_per_correlation", 0),
        ("max_reactive_turns_per_correlation", -1),
    ],
)
def test_runtime_config_api_limits_must_be_positive(field_name: str, value: int) -> None:
    from remora.core.model.config import RuntimeConfig

    with pytest.raises(ValidationError):
        RuntimeConfig(**{field_name: value})


@pytest.mark.parametrize("value", [-1, 6])
def test_runtime_config_max_model_retries_bounds(value: int) -> None:
    from remora.core.model.config import RuntimeConfig

    with pytest.raises(ValidationError):
        RuntimeConfig(max_model_retries=value)
