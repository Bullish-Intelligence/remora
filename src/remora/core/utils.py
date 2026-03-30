"""Shared utilities."""

from __future__ import annotations

from typing import Any


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overlay into base. Overlay wins for non-dict values."""
    result = dict(base)
    for key, value in overlay.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = deep_merge(existing, value)
        else:
            result[key] = value
    return result


def mask_secret(value: str | None, visible_chars: int = 4) -> str:
    """Mask a secret string for safe logging."""
    if not value:
        return "EMPTY"
    if len(value) <= visible_chars:
        return "****"
    return value[:visible_chars] + "****"


__all__ = ["deep_merge", "mask_secret"]
