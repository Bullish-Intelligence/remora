"""
Grail - Transparent Python for Monty.

A minimalist library for writing Monty code with full IDE support.
"""

import logging

logging.getLogger("grail").addHandler(logging.NullHandler())

__version__ = "3.0.0"

# Core functions
from grail.script import load, run, run_sync, GrailScript

# Declarations (for .pym files)
from grail._external import external
from grail._input import Input

# Limits
from grail.limits import Limits, STRICT, DEFAULT, PERMISSIVE

# Errors
from grail.errors import (
    GrailError,
    ParseError,
    CheckError,
    InputError,
    ExternalError,
    ExecutionError,
    LimitError,
    OutputError,
)

# Check result types
from grail._types import (
    CheckResult,
    CheckMessage,
    ScriptEvent,
    ExternalSpec,
    InputSpec,
    ParameterSpec,
    ParamKind,
)

# Define public API
__all__ = [
    # Core
    "load",
    "run",
    "run_sync",
    "GrailScript",
    # Declarations
    "external",
    "Input",
    # Limits
    "Limits",
    "STRICT",
    "DEFAULT",
    "PERMISSIVE",
    # Errors
    "GrailError",
    "ParseError",
    "CheckError",
    "InputError",
    "ExternalError",
    "ExecutionError",
    "LimitError",
    "OutputError",
    # Check results
    "CheckResult",
    "CheckMessage",
    # Events
    "ScriptEvent",
    # Types
    "ExternalSpec",
    "InputSpec",
    "ParameterSpec",
    "ParamKind",
]
