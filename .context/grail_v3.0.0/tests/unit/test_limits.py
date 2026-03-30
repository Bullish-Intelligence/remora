"""Test Limits model."""

import pytest
from pydantic import ValidationError

from grail.limits import Limits


# --- Construction & Parsing ---


class TestLimitsConstruction:
    """Test creating Limits instances with various input formats."""

    def test_create_with_string_memory(self):
        """String memory values should be parsed to bytes."""
        limits = Limits(max_memory="16mb")
        assert limits.max_memory == 16 * 1024 * 1024

    def test_create_with_string_memory_kb(self):
        limits = Limits(max_memory="512kb")
        assert limits.max_memory == 512 * 1024

    def test_create_with_string_memory_gb(self):
        limits = Limits(max_memory="1gb")
        assert limits.max_memory == 1024 * 1024 * 1024

    def test_create_with_string_memory_case_insensitive(self):
        limits = Limits(max_memory="16MB")
        assert limits.max_memory == 16 * 1024 * 1024

    def test_create_with_string_duration_ms(self):
        """String duration in ms should be parsed to seconds."""
        limits = Limits(max_duration="500ms")
        assert limits.max_duration == 0.5

    def test_create_with_string_duration_s(self):
        limits = Limits(max_duration="2s")
        assert limits.max_duration == 2.0

    def test_create_with_string_duration_fractional(self):
        limits = Limits(max_duration="1.5s")
        assert limits.max_duration == 1.5

    def test_create_with_int_recursion(self):
        limits = Limits(max_recursion=200)
        assert limits.max_recursion == 200

    def test_create_with_int_allocations(self):
        limits = Limits(max_allocations=10000)
        assert limits.max_allocations == 10000

    def test_create_with_int_gc_interval(self):
        limits = Limits(gc_interval=500)
        assert limits.gc_interval == 500

    def test_all_fields_none_by_default(self):
        """Omitted fields should be None."""
        limits = Limits()
        assert limits.max_memory is None
        assert limits.max_duration is None
        assert limits.max_recursion is None
        assert limits.max_allocations is None
        assert limits.gc_interval is None

    def test_create_with_all_fields(self):
        limits = Limits(
            max_memory="16mb",
            max_duration="2s",
            max_recursion=200,
            max_allocations=10000,
            gc_interval=500,
        )
        assert limits.max_memory == 16 * 1024 * 1024
        assert limits.max_duration == 2.0
        assert limits.max_recursion == 200
        assert limits.max_allocations == 10000
        assert limits.gc_interval == 500


# --- Validation & Errors ---


class TestLimitsValidation:
    """Test that invalid inputs are rejected."""

    def test_invalid_memory_format(self):
        with pytest.raises(ValidationError):
            Limits(max_memory="16")

    def test_invalid_memory_string(self):
        with pytest.raises(ValidationError):
            Limits(max_memory="not_a_size")

    def test_invalid_duration_format(self):
        with pytest.raises(ValidationError):
            Limits(max_duration="2")

    def test_invalid_duration_string(self):
        with pytest.raises(ValidationError):
            Limits(max_duration="not_a_duration")

    def test_unknown_field_rejected(self):
        """Unknown fields should raise ValidationError, not silently pass through."""
        with pytest.raises(ValidationError):
            Limits(max_mmeory="16mb")  # typo

    def test_frozen(self):
        """Limits should be immutable after creation."""
        limits = Limits(max_memory="16mb")
        with pytest.raises(ValidationError):
            limits.max_memory = 0


# --- Presets ---


class TestLimitsPresets:
    """Test preset class methods."""

    def test_strict_preset(self):
        limits = Limits.strict()
        assert limits.max_memory == 8 * 1024 * 1024
        assert limits.max_duration == 0.5
        assert limits.max_recursion == 120

    def test_default_preset(self):
        limits = Limits.default()
        assert limits.max_memory == 16 * 1024 * 1024
        assert limits.max_duration == 2.0
        assert limits.max_recursion == 200

    def test_permissive_preset(self):
        limits = Limits.permissive()
        assert limits.max_memory == 64 * 1024 * 1024
        assert limits.max_duration == 5.0
        assert limits.max_recursion == 400

    def test_presets_return_limits_instances(self):
        assert isinstance(Limits.strict(), Limits)
        assert isinstance(Limits.default(), Limits)
        assert isinstance(Limits.permissive(), Limits)


# --- Merging ---


class TestLimitsMerge:
    """Test merging two Limits instances."""

    def test_merge_override_takes_precedence(self):
        base = Limits(max_memory="16mb", max_recursion=200)
        override = Limits(max_memory="32mb")
        merged = base.merge(override)

        assert merged.max_memory == 32 * 1024 * 1024
        assert merged.max_recursion == 200

    def test_merge_preserves_base_when_override_is_none(self):
        base = Limits(max_memory="16mb", max_duration="2s")
        override = Limits()  # all None
        merged = base.merge(override)

        assert merged.max_memory == 16 * 1024 * 1024
        assert merged.max_duration == 2.0

    def test_merge_returns_new_instance(self):
        base = Limits(max_memory="16mb")
        override = Limits(max_duration="5s")
        merged = base.merge(override)

        assert merged is not base
        assert merged is not override
        assert merged.max_memory == 16 * 1024 * 1024
        assert merged.max_duration == 5.0

    def test_merge_all_fields(self):
        base = Limits(
            max_memory="16mb",
            max_duration="2s",
            max_recursion=200,
            max_allocations=10000,
            gc_interval=500,
        )
        override = Limits(max_memory="32mb", max_allocations=20000)
        merged = base.merge(override)

        assert merged.max_memory == 32 * 1024 * 1024
        assert merged.max_duration == 2.0
        assert merged.max_recursion == 200
        assert merged.max_allocations == 20000
        assert merged.gc_interval == 500


# --- Monty Conversion ---


class TestLimitsToMonty:
    """Test conversion to Monty-native dict format."""

    def test_to_monty_renames_keys(self):
        limits = Limits(max_memory="16mb", max_duration="2s", max_recursion=200)
        monty = limits.to_monty()

        assert monty == {
            "max_memory": 16 * 1024 * 1024,
            "max_duration_secs": 2.0,
            "max_recursion_depth": 200,
        }

    def test_to_monty_omits_none_fields(self):
        limits = Limits(max_memory="16mb")
        monty = limits.to_monty()

        assert monty == {"max_memory": 16 * 1024 * 1024}
        assert "max_duration_secs" not in monty
        assert "max_recursion_depth" not in monty

    def test_to_monty_all_fields(self):
        limits = Limits(
            max_memory="16mb",
            max_duration="2s",
            max_recursion=200,
            max_allocations=10000,
            gc_interval=500,
        )
        monty = limits.to_monty()

        assert monty == {
            "max_memory": 16 * 1024 * 1024,
            "max_duration_secs": 2.0,
            "max_recursion_depth": 200,
            "max_allocations": 10000,
            "gc_interval": 500,
        }

    def test_to_monty_empty_limits(self):
        limits = Limits()
        monty = limits.to_monty()

        assert monty == {}


# --- String Parsing Functions (preserved as internal helpers) ---


class TestParseMemoryString:
    """Test the memory string parser (used by Limits internally)."""

    def test_megabytes(self):
        from grail.limits import parse_memory_string

        assert parse_memory_string("16mb") == 16 * 1024 * 1024

    def test_gigabytes(self):
        from grail.limits import parse_memory_string

        assert parse_memory_string("1gb") == 1024 * 1024 * 1024

    def test_kilobytes(self):
        from grail.limits import parse_memory_string

        assert parse_memory_string("512kb") == 512 * 1024

    def test_case_insensitive(self):
        from grail.limits import parse_memory_string

        assert parse_memory_string("1MB") == 1024 * 1024

    def test_invalid_raises(self):
        from grail.limits import parse_memory_string

        with pytest.raises(ValueError, match="Invalid memory format"):
            parse_memory_string("16")


class TestParseDurationString:
    """Test the duration string parser (used by Limits internally)."""

    def test_milliseconds(self):
        from grail.limits import parse_duration_string

        assert parse_duration_string("500ms") == 0.5

    def test_seconds(self):
        from grail.limits import parse_duration_string

        assert parse_duration_string("2s") == 2.0

    def test_fractional_seconds(self):
        from grail.limits import parse_duration_string

        assert parse_duration_string("1.5s") == 1.5

    def test_invalid_raises(self):
        from grail.limits import parse_duration_string

        with pytest.raises(ValueError, match="Invalid duration format"):
            parse_duration_string("2")
