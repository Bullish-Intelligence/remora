"""Configuration for integration tests."""

import pytest


def pytest_configure(config):
    """Add integration marker."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires pydantic-monty)"
    )
