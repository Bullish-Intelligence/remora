"""Tests for the logging/event system."""

import time
from grail._types import ScriptEvent


def test_script_event_creation():
    """ScriptEvent can be created with required fields."""
    event = ScriptEvent(
        type="run_start",
        script_name="test",
        timestamp=time.time(),
    )
    assert event.type == "run_start"
    assert event.script_name == "test"
    assert event.text is None


def test_script_event_print():
    """ScriptEvent can represent print output."""
    event = ScriptEvent(
        type="print",
        script_name="test",
        timestamp=time.time(),
        text="hello world\n",
    )
    assert event.type == "print"
    assert event.text == "hello world\n"


def test_script_event_run_complete():
    """ScriptEvent can represent run completion."""
    event = ScriptEvent(
        type="run_complete",
        script_name="test",
        timestamp=time.time(),
        duration_ms=42.5,
        result_summary="dict",
    )
    assert event.duration_ms == 42.5


def test_script_event_run_error():
    """ScriptEvent can represent run failure."""
    event = ScriptEvent(
        type="run_error",
        script_name="test",
        timestamp=time.time(),
        error="NameError: x is not defined",
    )
    assert event.error is not None
