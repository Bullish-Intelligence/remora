"""Shared exceptions for remora core."""

from __future__ import annotations


class RemoraError(Exception):
    """Base for all expected Remora failures."""


class ModelError(RemoraError):
    """LLM backend failures — timeouts, rate limits, API errors."""


class ToolError(RemoraError):
    """Grail tool script execution failures."""


class WorkspaceError(RemoraError):
    """Cairn workspace / filesystem failures."""


class SubscriptionError(RemoraError):
    """Event routing or subscription matching failures."""


class IncompatibleBundleError(RemoraError):
    """Raised when a bundle's externals version exceeds the runtime's."""

    def __init__(self, bundle_version: int, runtime_version: int) -> None:
        self.bundle_version = bundle_version
        self.runtime_version = runtime_version
        super().__init__(
            f"Bundle requires externals version {bundle_version}, "
            f"but runtime supports version {runtime_version}"
        )


__all__ = [
    "RemoraError",
    "ModelError",
    "ToolError",
    "WorkspaceError",
    "SubscriptionError",
    "IncompatibleBundleError",
]
