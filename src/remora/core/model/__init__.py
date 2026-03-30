"""Domain model — what things ARE."""

from remora.core.model.config import (
    BehaviorConfig,
    BundleConfig,
    BundleOverlayRule,
    Config,
    InfraConfig,
    ProjectConfig,
    RuntimeConfig,
    SearchConfig,
    SearchMode,
    SelfReflectConfig,
    VirtualAgentConfig,
    VirtualSubscriptionConfig,
    expand_env_vars,
    expand_string,
    load_config,
    resolve_bundle_dirs,
    resolve_bundle_search_paths,
    resolve_query_search_paths,
)
from remora.core.model.errors import IncompatibleBundleError
from remora.core.model.node import Node
from remora.core.model.types import (
    STATUS_TRANSITIONS,
    ChangeType,
    EventType,
    NodeStatus,
    NodeType,
    serialize_enum,
    validate_status_transition,
)
