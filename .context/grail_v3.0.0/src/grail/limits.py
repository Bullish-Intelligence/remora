"""Resource limits for script execution."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


def parse_memory_string(value: str) -> int:
    """
    Parse memory string to bytes.

    Examples:
        "16mb" -> 16777216
        "1gb"  -> 1073741824
        "512kb" -> 524288

    Raises:
        ValueError: If format is invalid.
    """
    value = value.lower().strip()
    match = re.match(r"^(\d+(?:\.\d+)?)(kb|mb|gb)$", value)
    if not match:
        raise ValueError(f"Invalid memory format: {value}. Use format like '16mb', '1gb'")

    number, unit = match.groups()
    multipliers = {"kb": 1024, "mb": 1024**2, "gb": 1024**3}
    return int(float(number) * multipliers[unit])


def parse_duration_string(value: str) -> float:
    """
    Parse duration string to seconds.

    Examples:
        "500ms" -> 0.5
        "2s"    -> 2.0

    Raises:
        ValueError: If format is invalid.
    """
    value = value.lower().strip()
    match = re.match(r"^(\d+(?:\.\d+)?)(ms|s)$", value)
    if not match:
        raise ValueError(f"Invalid duration format: {value}. Use format like '500ms', '2s'")

    number, unit = match.groups()
    number = float(number)
    return number / 1000.0 if unit == "ms" else number


class Limits(BaseModel, frozen=True):
    """
    Resource limits for script execution.

    All fields are optional. Omit a field (or pass None) to leave that
    limit unconstrained.

    Memory and duration accept human-readable strings:
        Limits(max_memory="16mb", max_duration="2s")

    Use presets for common configurations:
        Limits.strict()
        Limits.default()
        Limits.permissive()
    """

    model_config = ConfigDict(extra="forbid")

    max_memory: int | None = None
    """Maximum heap memory in bytes. Accepts strings like '16mb', '1gb'."""

    max_duration: float | None = None
    """Maximum execution time in seconds. Accepts strings like '500ms', '2s'."""

    max_recursion: int | None = None
    """Maximum function call stack depth."""

    max_allocations: int | None = None
    """Maximum number of heap allocations allowed."""

    gc_interval: int | None = None
    """Run garbage collection every N allocations."""

    @field_validator("max_memory", mode="before")
    @classmethod
    def _parse_memory(cls, v: Any) -> int | None:
        if v is None:
            return None
        if isinstance(v, str):
            return parse_memory_string(v)
        return v

    @field_validator("max_duration", mode="before")
    @classmethod
    def _parse_duration(cls, v: Any) -> float | None:
        if v is None:
            return None
        if isinstance(v, str):
            return parse_duration_string(v)
        return v

    # --- Presets ---

    @classmethod
    def strict(cls) -> Limits:
        """Tight limits for untrusted code."""
        return cls(
            max_memory=parse_memory_string("8mb"),
            max_duration=parse_duration_string("500ms"),
            max_recursion=120,
        )

    @classmethod
    def default(cls) -> Limits:
        """Balanced defaults for typical scripts."""
        return cls(
            max_memory=parse_memory_string("16mb"),
            max_duration=parse_duration_string("2s"),
            max_recursion=200,
        )

    @classmethod
    def permissive(cls) -> Limits:
        """Relaxed limits for trusted or heavy workloads."""
        return cls(
            max_memory=parse_memory_string("64mb"),
            max_duration=parse_duration_string("5s"),
            max_recursion=400,
        )

    # --- Merging ---

    def merge(self, overrides: Limits) -> Limits:
        """
        Return a new Limits with override values taking precedence.

        Only non-None fields in `overrides` replace the base values.
        """
        return Limits(
            max_memory=overrides.max_memory
            if overrides.max_memory is not None
            else self.max_memory,
            max_duration=overrides.max_duration
            if overrides.max_duration is not None
            else self.max_duration,
            max_recursion=overrides.max_recursion
            if overrides.max_recursion is not None
            else self.max_recursion,
            max_allocations=overrides.max_allocations
            if overrides.max_allocations is not None
            else self.max_allocations,
            gc_interval=overrides.gc_interval
            if overrides.gc_interval is not None
            else self.gc_interval,
        )

    # --- Monty Conversion ---

    def to_monty(self) -> dict[str, Any]:
        """
        Convert to the dict format expected by ``pydantic_monty.run_monty_async()``.

        Key renames:
            max_duration  -> max_duration_secs
            max_recursion -> max_recursion_depth
        """
        mapping: list[tuple[str, str]] = [
            ("max_memory", "max_memory"),
            ("max_duration", "max_duration_secs"),
            ("max_recursion", "max_recursion_depth"),
            ("max_allocations", "max_allocations"),
            ("gc_interval", "gc_interval"),
        ]
        result: dict[str, Any] = {}
        for attr, monty_key in mapping:
            value = getattr(self, attr)
            if value is not None:
                result[monty_key] = value
        return result


STRICT: dict[str, Any] = Limits.strict().to_monty()
DEFAULT: dict[str, Any] = Limits.default().to_monty()
PERMISSIVE: dict[str, Any] = Limits.permissive().to_monty()
