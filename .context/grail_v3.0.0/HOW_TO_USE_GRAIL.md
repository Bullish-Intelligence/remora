# How to Use Grail: A Developer Integration Guide

Grail is a Python library that enables sandboxed script execution via
[Monty](https://pypi.org/project/pydantic-monty/), a secure Python interpreter
written in Rust. You write `.pym` files (a restricted Python dialect), and Grail
parses, validates, code-generates, and executes them inside an isolated runtime
where scripts cannot access the filesystem, network, or arbitrary modules.

This guide is for **library and application developers** who want to integrate
Grail into their own projects to let users (or their own systems) run sandboxed
logic safely.

---

## Table of Contents

1. [Installation](#1-installation)
2. [Core Concepts](#2-core-concepts)
3. [Quick Start](#3-quick-start)
4. [Writing .pym Scripts](#4-writing-pym-scripts)
   - [File Structure](#41-file-structure)
   - [Imports](#42-imports)
   - [Declaring Inputs](#43-declaring-inputs)
   - [Declaring External Functions](#44-declaring-external-functions)
   - [Executable Code](#45-executable-code)
   - [Returning Values](#46-returning-values)
   - [Supported Python Features](#47-supported-python-features)
   - [Forbidden Python Features](#48-forbidden-python-features)
5. [Integrating Grail Into Your Code](#5-integrating-grail-into-your-code)
   - [Loading Scripts](#51-loading-scripts)
   - [Running Scripts (Async)](#52-running-scripts-async)
   - [Running Scripts (Sync)](#53-running-scripts-sync)
   - [Providing External Functions](#54-providing-external-functions)
   - [Providing Inputs](#55-providing-inputs)
   - [Output Validation with Pydantic Models](#56-output-validation-with-pydantic-models)
   - [Running Inline Code (No .pym File)](#57-running-inline-code-no-pym-file)
   - [Lifecycle Events](#58-lifecycle-events)
   - [Print Capture](#59-print-capture)
6. [Resource Limits](#6-resource-limits)
   - [Presets](#61-presets)
   - [Custom Limits](#62-custom-limits)
   - [Merging Limits](#63-merging-limits)
7. [Virtual Filesystem and Environment Variables](#7-virtual-filesystem-and-environment-variables)
8. [The .grail/ Directory](#8-the-grail-directory)
   - [What Gets Generated](#81-what-gets-generated)
   - [Disabling Artifacts](#82-disabling-artifacts)
   - [Cleaning Up](#83-cleaning-up)
   - [Git Integration](#84-git-integration)
9. [Static Validation (Checking Scripts)](#9-static-validation-checking-scripts)
10. [Error Handling](#10-error-handling)
    - [Error Hierarchy](#101-error-hierarchy)
    - [Catching Specific Errors](#102-catching-specific-errors)
    - [Error Details](#103-error-details)
    - [Important: LimitError Is Not an ExecutionError](#104-important-limiterror-is-not-an-executionerror)
11. [Dataclass Registry](#11-dataclass-registry)
12. [CLI Reference](#12-cli-reference)
13. [Validation Codes Reference](#13-validation-codes-reference)
14. [Scope of Work for .pym Scripts](#14-scope-of-work-for-pym-scripts)
15. [Complete Integration Example](#15-complete-integration-example)

---

## 1. Installation

Requires **Python >= 3.13**.

```bash
pip install grail
```

For file-watching support (optional):

```bash
pip install grail[watch]
```

Dependencies: `pydantic >= 2.12.5`, `pydantic-monty`.

---

## 2. Core Concepts

| Concept           | Description |
|-------------------|-------------|
| `.pym` file       | A restricted Python file with `@external` and `Input()` declarations. This is what script authors write. |
| `@external`       | A decorator that declares a function the **host** will provide at runtime. The script declares the signature; your code supplies the implementation. |
| `Input()`         | A function that declares a named value the host will inject at runtime. |
| `GrailScript`     | The main class you interact with. Created by `grail.load()`. Encapsulates parsed metadata, generated code, and provides `check()`, `run()`, and `run_sync()`. |
| Monty             | The sandboxed Python interpreter (Rust-based) that actually executes the code. Grail wraps Monty transparently. |
| `Limits`          | A Pydantic model controlling memory, duration, recursion, and allocation limits. |
| `.grail/`         | An optional artifacts directory containing generated stubs, Monty code, check results, and run logs. |

### The Pipeline

```
.pym file
   │
   ├─ 1. Parse ──────────── Extract @external specs, Input() specs, AST
   │
   ├─ 2. Check ──────────── Validate Monty compatibility (E001–E012)
   │                         Validate declarations (E006–E008)
   │                         Check warnings (W001–W004)
   │
   ├─ 3. Generate stubs ─── .pyi stubs for Monty's type checker
   │
   ├─ 4. Generate code ──── Strip declarations, produce clean Monty code
   │                         Build source map (.pym line ↔ Monty line)
   │
   └─ 5. Execute ─────────── Run in Monty sandbox with inputs + externals
                              Map errors back to .pym line numbers
```

---

## 3. Quick Start

**`analysis.pym`** — the sandboxed script:

```python
from grail import external, Input
from typing import Any

# Declare inputs the host will provide
budget: float = Input("budget")

# Declare functions the host will implement
@external
async def get_expenses(user_id: int) -> list[dict[str, Any]]:
    """Fetch expenses from the database."""
    ...

# Executable logic
expenses = await get_expenses(user_id=1)
total = sum(item["amount"] for item in expenses)

# Return a result (last expression)
{"total": total, "over_budget": total > budget}
```

**`host.py`** — your application code:

```python
import asyncio
from grail import load

async def main():
    # 1. Load and validate
    script = load("analysis.pym")

    # 2. Execute with real implementations
    result = await script.run(
        inputs={"budget": 5000.0},
        externals={
            "get_expenses": my_get_expenses_impl,
        },
    )

    print(result)  # {"total": 7500.0, "over_budget": True}

async def my_get_expenses_impl(user_id: int) -> list[dict[str, Any]]:
    # Your real database/API call here
    return [{"amount": 3000.0}, {"amount": 4500.0}]

asyncio.run(main())
```

---

## 4. Writing .pym Scripts

A `.pym` file is **valid Python** (any IDE will provide syntax highlighting and
autocomplete) with a specific structure. The Grail pipeline strips the
declaration boilerplate before execution, so the Monty sandbox only sees clean
executable code.

### 4.1 File Structure

Every `.pym` follows this order:

```python
# 1. Imports (grail and typing only)
from grail import external, Input
from typing import Any, Optional

# 2. Input declarations
name: type = Input("name")
name: type = Input("name", default=value)

# 3. External function declarations
@external
async def function_name(param: type) -> return_type:
    """Optional docstring."""
    ...

# 4. Executable logic
result = await function_name(param_value)

# 5. Return value (last expression)
result
```

### 4.2 Imports

Only three modules are allowed:

| Module       | Purpose |
|--------------|---------|
| `grail`      | `external` decorator and `Input()` function |
| `typing`     | Type annotations (`Any`, `Optional`, `Dict`, `List`, etc.) |
| `__future__` | Future annotations |

Any other import triggers error **E005** and the script will not load.

```python
# OK
from grail import external, Input
from typing import Any, Optional, Dict, List

# FORBIDDEN — will raise CheckError
import json        # E005
import os          # E005
from pathlib import Path  # E005
```

### 4.3 Declaring Inputs

Inputs are values the host injects at runtime. Declare them at the top level
with a type annotation and an `Input()` call:

```python
# Required input (no default)
budget: float = Input("budget")

# Optional input (has a default)
department: str = Input("department", default="Engineering")
```

**Rules:**

- The `Input()` name argument **must match** the variable name.
  `budget: float = Input("budget")` is valid; `budget: float = Input("cost")`
  will raise an error.
- A type annotation is **required** (error E008 without one).
- Inputs without a `default` are **required** — the host must provide them at
  `run()` time or `InputError` is raised.
- Inputs are only extracted at the **top level** of the file. An `Input()` call
  nested inside a function is ignored.

### 4.4 Declaring External Functions

External functions are the script's way of calling out to the host environment.
The script declares the **signature**; the host provides the **implementation**.

```python
@external
async def fetch_data(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Fetch data from the source. Host provides the implementation."""
    ...
```

**Rules:**

- The decorator must be `@external` (or `@grail.external`).
- The function body must be `...` (Ellipsis) — optionally preceded by a
  docstring. No real code. (Error E007 otherwise.)
- **All parameters must have type annotations** (error E006).
- **A return type annotation is required** (error E006).
- Both `async def` and `def` are supported. If declared `async`, the script
  calls it with `await`.
- Default parameter values are supported.
- All five Python parameter kinds work: positional-only (`/`),
  positional-or-keyword, `*args`, keyword-only, `**kwargs`.
- Externals are only extracted at the **top level**. A decorated function nested
  inside another function is ignored by the parser.

```python
# Sync external
@external
def compute(x: int, y: int) -> int:
    ...

# Async external
@external
async def fetch(url: str) -> str:
    ...

# With docstring and defaults
@external
async def search(query: str, max_results: int = 50) -> list[str]:
    """Search the index. Returns matching document IDs."""
    ...
```

### 4.5 Executable Code

Everything after the declarations is the script's logic. This code runs inside
the Monty sandbox.

```python
# Call externals
data = await fetch_data(query="revenue", limit=5)

# Standard Python logic
total = 0.0
for record in data:
    if record["status"] == "active":
        total += record["amount"]

# Helper functions (regular def, not @external)
def format_currency(amount: float) -> str:
    return f"${amount:,.2f}"

formatted = format_currency(total)
```

### 4.6 Returning Values

The **last expression** in the script is its return value. It is the value
returned by `script.run()`.

```python
# Return a dict
{"total": total, "formatted": formatted, "count": len(data)}
```

```python
# Return a simple value
total
```

```python
# Assign then return
result = {"total": total}
result
```

If the script has no trailing expression, `run()` returns `None`.

> **Warning W001:** A bare dict literal (`{...}`) as the final expression
> triggers a style warning suggesting you assign it to a variable first. This is
> non-blocking.

### 4.7 Supported Python Features

| Feature | Example | Notes |
|---------|---------|-------|
| Variables | `x = 10` | |
| Arithmetic | `x + y * 2` | |
| String operations | `f"Hello {name}"` | f-strings supported |
| Functions (`def`) | `def helper(x): ...` | Regular (non-external) functions |
| `async`/`await` | `result = await fetch()` | For calling async externals |
| `if`/`elif`/`else` | Standard conditional logic | |
| `for` loops | `for item in items:` | |
| `while` loops | `while condition:` | |
| `try`/`except` | `try: ... except ValueError: ...` | |
| `try`/`finally` | `try: ... finally: ...` | |
| List comprehensions | `[x*2 for x in items]` | |
| Dict comprehensions | `{k: v for k, v in pairs}` | |
| Generator expressions | `sum(x for x in items)` | Inside function calls only |
| Type annotations | `x: int = 5` | |
| `print()` | `print("debug")` | Captured via callback |
| `os.getenv()` | `os.getenv("KEY")` | Only virtual env vars |
| Nested functions | `def outer(): def inner(): ...` | |
| Tuples, lists, dicts | Standard collection literals | |
| Slicing | `items[1:3]` | |
| Boolean logic | `and`, `or`, `not` | |
| Ternary | `x if condition else y` | |
| Unpacking | `a, b = (1, 2)` | |
| String methods | `s.upper()`, `s.split()` | |
| `isinstance()` | `isinstance(x, int)` | Also for registered dataclasses |

### 4.8 Forbidden Python Features

These produce **errors** during `load()` and prevent execution:

| Code | Feature | Suggestion |
|------|---------|------------|
| E001 | `class` definitions | Use functions and dicts |
| E002 | `yield` / `yield from` (generators) | Return a list instead |
| E003 | `with` statements | Use `try`/`finally` or external functions |
| E004 | `match` statements | Use `if`/`elif`/`else` |
| E005 | Any import except `grail`, `typing`, `__future__` | Move logic to externals |
| E006 | Missing type annotations on `@external` params or return type | Add annotations |
| E007 | `@external` body with real code (not `...`) | Replace body with `...` |
| E008 | `Input()` without a type annotation | Add annotation |
| E009 | `global` statement | Use params/returns |
| E010 | `nonlocal` statement | Use params/returns |
| E011 | `del` statement | Don't delete variables |
| E012 | `lambda` expressions | Use `def` instead |

---

## 5. Integrating Grail Into Your Code

### 5.1 Loading Scripts

```python
from grail import load, Limits

# Basic load (validates and prepares the script)
script = load("path/to/script.pym")

# Load with resource limits
script = load("script.pym", limits=Limits.strict())

# Load with a virtual filesystem
script = load("script.pym", files={
    "/data/config.json": '{"key": "value"}',
    "/data/input.csv": b"col1,col2\n1,2\n",
})

# Load with virtual environment variables
script = load("script.pym", environ={"API_KEY": "abc123"})

# Load without artifact generation
script = load("script.pym", grail_dir=None)

# Load with custom artifact directory
script = load("script.pym", grail_dir=".my_artifacts")
```

`load()` does the full pipeline: parse → check → generate stubs → generate
code → write artifacts. If the script has **any** validation errors (codes
starting with "E"), `load()` raises `CheckError` immediately.

**`load()` signature:**

```python
def load(
    path: str | Path,
    limits: Limits | None = None,
    files: dict[str, str | bytes] | None = None,
    environ: dict[str, str] | None = None,
    grail_dir: str | Path | None = ".grail",  # default
    dataclass_registry: list[type] | None = None,
) -> GrailScript
```

### 5.2 Running Scripts (Async)

`run()` is async. Use it in async contexts:

```python
result = await script.run(
    inputs={"budget": 5000.0, "department": "Engineering"},
    externals={
        "get_expenses": my_expenses_function,
        "get_team": my_team_function,
    },
)
```

**`run()` signature:**

```python
async def run(
    self,
    inputs: dict[str, Any] | None = None,
    externals: dict[str, Callable] | None = None,
    output_model: type[BaseModel] | None = None,
    files: dict[str, str | bytes] | None = None,
    environ: dict[str, str] | None = None,
    limits: Limits | None = None,
    print_callback: Callable[[Literal["stdout"], str], None] | None = None,
    on_event: Callable[[ScriptEvent], None] | None = None,
    strict_validation: bool = True,
) -> Any
```

### 5.3 Running Scripts (Sync)

For synchronous code (no event loop running):

```python
result = script.run_sync(
    inputs={"budget": 5000.0},
    externals={"get_expenses": my_expenses_function},
)
```

`run_sync()` calls `asyncio.run()` internally. If called from within an async
context (e.g., inside an `async def`, a Jupyter notebook, or FastAPI), it raises
`RuntimeError`. Use `await script.run()` in those cases.

### 5.4 Providing External Functions

Every `@external` declared in the `.pym` script **must** have a corresponding
entry in the `externals` dict at `run()` time (unless `strict_validation=False`).

```python
# .pym declares:
#   @external
#   async def fetch_data(query: str) -> list[dict[str, Any]]:
#       ...

# Host provides:
async def my_fetch_data(query: str) -> list[dict[str, Any]]:
    return await database.query(query)

result = await script.run(
    externals={"fetch_data": my_fetch_data},
)
```

**Key behaviors:**

- **Missing external → `ExternalError`** (always, even in non-strict mode).
- **Extra external (not declared in script) → `ExternalError`** in strict mode
  (default), or a `UserWarning` in non-strict mode.
- Sync externals work for sync `@external` declarations; async externals work
  for `async def @external` declarations.
- If your external raises an exception, it propagates through Monty and is
  mapped to an `ExecutionError` with the original exception type name preserved
  in the message (e.g., `"ValueError: invalid input"`).

### 5.5 Providing Inputs

Every `Input()` without a `default` is **required**. Provide them via the
`inputs` dict:

```python
# .pym declares:
#   budget: float = Input("budget")                          # required
#   department: str = Input("department", default="Sales")   # optional

result = await script.run(
    inputs={"budget": 5000.0},  # department uses default "Sales"
)

result = await script.run(
    inputs={"budget": 5000.0, "department": "Engineering"},  # override default
)
```

**Key behaviors:**

- **Missing required input → `InputError`**.
- **Extra input (not declared in script) → `InputError`** in strict mode, or
  `UserWarning` in non-strict mode.
- Pass `strict_validation=False` to `run()` to downgrade extra input/external
  errors to warnings.

### 5.6 Output Validation with Pydantic Models

Pass a Pydantic `BaseModel` as `output_model` to validate the script's return
value:

```python
from pydantic import BaseModel

class AnalysisResult(BaseModel):
    total: float
    over_budget: bool
    details: list[dict]

result = await script.run(
    inputs={...},
    externals={...},
    output_model=AnalysisResult,
)
# result is now an AnalysisResult instance, validated
print(result.total)
```

If the return value doesn't match the model, `OutputError` is raised.

### 5.7 Running Inline Code (No .pym File)

For quick, one-off execution of Monty code without a `.pym` file:

```python
import grail

# Async
result = await grail.run("x + y", inputs={"x": 1, "y": 2})
# result == 3

# Sync
result = grail.run_sync("x * 2", inputs={"x": 21})
# result == 42
```

These functions skip the full `.pym` pipeline (no `@external`/`Input()`
parsing, no static checks, no source mapping). Use `load()` for production.

**`grail.run()` signature:**

```python
async def run(
    code: str,
    *,
    inputs: dict[str, Any] | None = None,
    limits: Limits | None = None,
    environ: dict[str, str] | None = None,
    print_callback: Callable[[Literal["stdout"], str], None] | None = None,
) -> Any
```

### 5.8 Lifecycle Events

Subscribe to structured events during `check()` and `run()`:

```python
from grail import ScriptEvent

def on_event(event: ScriptEvent):
    print(f"[{event.type}] {event.script_name} @ {event.timestamp}")
    if event.type == "print":
        print(f"  Script printed: {event.text}")
    if event.type == "run_complete":
        print(f"  Duration: {event.duration_ms:.1f}ms")
    if event.type == "run_error":
        print(f"  Error: {event.error}")

result = await script.run(
    inputs={...},
    externals={...},
    on_event=on_event,
)
```

**Event types:**

| Type | When | Notable Fields |
|------|------|----------------|
| `run_start` | Before execution begins | `input_count`, `external_count` |
| `run_complete` | After successful execution | `duration_ms`, `result_summary` |
| `run_error` | After execution failure | `duration_ms`, `error` |
| `print` | When script calls `print()` | `text` |
| `check_start` | Before validation | |
| `check_complete` | After validation | `result_summary` |

### 5.9 Print Capture

Capture `print()` output from inside the sandbox:

```python
def on_print(stream: str, text: str):
    # stream is always "stdout"
    log.info(f"Script output: {text}")

result = await script.run(
    inputs={...},
    externals={...},
    print_callback=on_print,
)
```

---

## 6. Resource Limits

Grail enforces resource limits through Monty to prevent runaway scripts.

### 6.1 Presets

```python
from grail import Limits

Limits.strict()      # 8 MB memory, 500ms duration, 120 recursion depth
Limits.default()     # 16 MB memory, 2s duration, 200 recursion depth
Limits.permissive()  # 64 MB memory, 5s duration, 400 recursion depth
```

### 6.2 Custom Limits

```python
# Human-readable strings
limits = Limits(
    max_memory="32mb",       # supports kb, mb, gb (case-insensitive)
    max_duration="1.5s",     # supports ms, s
    max_recursion=300,
    max_allocations=100000,
    gc_interval=5000,
)

# Integer/float values
limits = Limits(
    max_memory=33554432,     # bytes
    max_duration=1.5,        # seconds
)
```

**Fields (all optional — omit or `None` to leave unconstrained):**

| Field | Type | Description |
|-------|------|-------------|
| `max_memory` | `int \| str \| None` | Max heap memory in bytes (or `"16mb"`) |
| `max_duration` | `float \| str \| None` | Max execution time in seconds (or `"2s"`) |
| `max_recursion` | `int \| None` | Max call stack depth |
| `max_allocations` | `int \| None` | Max number of heap allocations |
| `gc_interval` | `int \| None` | GC frequency (every N allocations) |

`Limits` is a **frozen** Pydantic model — immutable after creation, rejects
unknown fields (typos like `max_mmeory` raise a validation error).

### 6.3 Merging Limits

Set defaults at load time, override per-execution:

```python
# Set base limits at load time
script = load("script.pym", limits=Limits.default())

# Override duration for this specific run
result = await script.run(
    inputs={...},
    externals={...},
    limits=Limits(max_duration="10s"),  # only override duration
)
```

Merging replaces only non-`None` fields from the override. All other fields
keep the base value. If no limits are set anywhere, `Limits.default()` is used.

---

## 7. Virtual Filesystem and Environment Variables

Scripts cannot access the real filesystem or environment. Instead, you provide
virtual files and env vars:

```python
script = load(
    "script.pym",
    files={
        "/data/config.json": '{"key": "value"}',
        "/data/input.csv": b"raw,bytes,here",
    },
    environ={
        "API_KEY": "abc123",
        "ENV": "production",
    },
)
```

Inside the script, the script can:
- Read virtual files (through Monty's sandboxed file access)
- Call `os.getenv("API_KEY")` to get `"abc123"`

You can override files and environ per-run:

```python
result = await script.run(
    inputs={...},
    externals={...},
    files={"/data/config.json": '{"key": "override"}'},  # replaces load-time files
    environ={"API_KEY": "different_key"},                  # replaces load-time environ
)
```

Run-time overrides **completely replace** load-time values (they don't merge).

---

## 8. The .grail/ Directory

### 8.1 What Gets Generated

When `grail_dir` is set (default: `".grail"`), Grail creates a per-script
subdirectory with diagnostic artifacts:

```
.grail/
└── <script_name>/
    ├── stubs.pyi        # Type stubs sent to Monty's type checker
    ├── monty_code.py    # Actual code executed by Monty (declarations stripped)
    ├── check.json       # Validation results (errors, warnings, info)
    ├── externals.json   # External function specifications
    ├── inputs.json      # Input specifications
    └── run.log          # Execution log (status, duration, stdout, stderr)
```

**`stubs.pyi`** — Generated type stubs so Monty's type checker knows the
signatures of externals and the types of inputs.

**`monty_code.py`** — The clean Python code with all Grail declarations
stripped. Starts with an auto-generated header comment. This is exactly what
Monty executes.

**`check.json`** — JSON with validation results including `valid` (bool),
`errors`, `warnings`, and `info` (external count, input count, lines of code,
features used).

**`externals.json`** / **`inputs.json`** — Serialized specifications for
debugging and tooling.

**`run.log`** — Written after each `run()`. Contains success/failure status,
duration in milliseconds, stdout capture, and stderr (error messages on
failure).

### 8.2 Disabling Artifacts

```python
script = load("script.pym", grail_dir=None)
```

### 8.3 Cleaning Up

Programmatic (via `ArtifactsManager`):

```python
from grail.artifacts import ArtifactsManager

manager = ArtifactsManager(Path(".grail"))
manager.clean()  # removes entire .grail/ directory
```

CLI:

```bash
grail clean
```

### 8.4 Git Integration

Add `.grail/` to your `.gitignore`. The `grail init` CLI command does this
automatically:

```bash
grail init
# Creates .grail/, adds it to .gitignore, creates example.pym
```

---

## 9. Static Validation (Checking Scripts)

After loading, you can re-run validation checks:

```python
script = load("script.pym")
check_result = script.check()

if not check_result.valid:
    for error in check_result.errors:
        print(f"[{error.code}] Line {error.lineno}: {error.message}")
        if error.suggestion:
            print(f"  Suggestion: {error.suggestion}")

for warning in check_result.warnings:
    print(f"[{warning.code}] Line {warning.lineno}: {warning.message}")

# Access all messages (errors + warnings) combined
for msg in check_result.messages:
    print(f"[{msg.severity}] {msg.code}: {msg.message}")

# Info dict
print(check_result.info)
# {"externals_count": 2, "inputs_count": 1, "lines_of_code": 30,
#  "monty_features_used": ["async_await", "for_loop"]}
```

Note: `check()` also runs Monty's type checker (error code E100 for type
errors). The `check()` method uses a **cached parse result** from `load()` time
to avoid TOCTOU issues — if the file changes on disk after `load()`, `check()`
still validates the originally-loaded version.

---

## 10. Error Handling

### 10.1 Error Hierarchy

```
GrailError (Exception)
├── ParseError          # .pym file has Python syntax errors
├── CheckError          # @external / Input() declarations are malformed
├── InputError          # Runtime input mismatch (missing/extra)
├── ExternalError       # Runtime external mismatch (missing/extra)
├── ExecutionError      # Monty runtime error (NameError, TypeError, etc.)
├── LimitError          # Resource limit exceeded (memory/duration/recursion)
└── OutputError         # output_model validation failed
```

All errors are importable from the top-level `grail` package.

### 10.2 Catching Specific Errors

```python
from grail import (
    load, GrailError, ParseError, CheckError,
    InputError, ExternalError, ExecutionError,
    LimitError, OutputError,
)

try:
    script = load("script.pym")
    result = await script.run(inputs={...}, externals={...})
except ParseError as e:
    print(f"Syntax error at line {e.lineno}: {e.message}")
except CheckError as e:
    print(f"Validation failed: {e.message}")
except InputError as e:
    print(f"Input problem with '{e.input_name}': {e.message}")
except ExternalError as e:
    print(f"External problem with '{e.function_name}': {e.message}")
except LimitError as e:
    print(f"Resource limit hit ({e.limit_type}): {e}")
except ExecutionError as e:
    print(f"Runtime error at line {e.lineno}: {e.message}")
    if e.source_context:
        print(e.source_context)
except OutputError as e:
    print(f"Output invalid: {e.message}")
except GrailError as e:
    print(f"Grail error: {e}")
```

### 10.3 Error Details

**`ParseError`:**
- `message: str` — error description
- `lineno: int | None` — line number
- `col_offset: int | None` — column offset

**`CheckError`:**
- `message: str` — summary of all validation errors
- `lineno: int | None` — line number

**`InputError`:**
- `message: str` — what went wrong
- `input_name: str | None` — which input caused it

**`ExternalError`:**
- `message: str` — what went wrong
- `function_name: str | None` — which external caused it

**`ExecutionError`:**
- `message: str` — error message (preserves original exception type, e.g., `"ZeroDivisionError: division by zero"`)
- `lineno: int | None` — mapped back to the `.pym` line number
- `col_offset: int | None` — column offset
- `source_context: str | None` — source code around the error
- `suggestion: str | None` — fix suggestion

**`LimitError`:**
- `limit_type: str | None` — one of `"memory"`, `"duration"`, `"recursion"`, `"allocations"`, or `None`

**`OutputError`:**
- `message: str` — what failed
- `validation_errors: Exception | None` — the underlying Pydantic validation exception

### 10.4 Important: LimitError Is Not an ExecutionError

`LimitError` inherits directly from `GrailError`, **not** from
`ExecutionError`. This is intentional — resource limits are a fundamentally
different category than code bugs.

```python
try:
    result = await script.run(...)
except ExecutionError:
    # This does NOT catch LimitError!
    print("Script had a bug")
except LimitError:
    # Must be caught separately
    print("Script exceeded resource limits")
```

If you want to catch both, catch `GrailError` or catch them individually.

---

## 11. Dataclass Registry

To allow `isinstance()` checks on custom dataclass types inside the sandbox,
pass them via `dataclass_registry`:

```python
from dataclasses import dataclass

@dataclass
class Person:
    name: str
    age: int

script = load("script.pym", dataclass_registry=[Person])

result = await script.run(
    inputs={"person": Person(name="Alice", age=30)},
    externals={...},
)
```

The script can then use `isinstance(person, Person)` and access `.name`,
`.age`.

---

## 12. CLI Reference

Grail provides a CLI for development workflows:

```bash
# Initialize project (creates .grail/, .gitignore entry, example.pym)
grail init

# Validate .pym files
grail check script.pym
grail check script.pym --format json     # JSON output
grail check script.pym --strict           # Treat warnings as errors

# Run a .pym file with a host module
grail run script.pym --host host.py
grail run script.pym --host host.py --input budget=5000 --input dept=eng

# Watch for changes and re-check
grail watch                               # Watch current directory
grail watch ./scripts                     # Watch specific directory
grail watch --strict

# Clean artifacts
grail clean

# Version
grail --version
```

The `--host` file for `grail run` must define a `main(script, inputs)` function
that calls `script.run()`.

---

## 13. Validation Codes Reference

### Errors (block loading)

| Code | Trigger | Suggestion |
|------|---------|------------|
| E001 | Class definition | Use functions and dicts |
| E002 | `yield` / `yield from` | Return a list |
| E003 | `with` statement | Use `try`/`finally` or external functions |
| E004 | `match` statement | Use `if`/`elif`/`else` |
| E005 | Forbidden import | Only `grail`, `typing`, `__future__` |
| E006 | Missing type annotation on `@external` | Add type annotations |
| E007 | `@external` body is not `...` | Replace body with `...` |
| E008 | `Input()` without type annotation | Add type annotation |
| E009 | `global` statement | Use params/returns |
| E010 | `nonlocal` statement | Use params/returns |
| E011 | `del` statement | Avoid deletion |
| E012 | `lambda` expression | Use `def` instead |
| E100 | Monty type checker error | Fix the type error |

### Warnings (non-blocking)

| Code | Trigger | Suggestion |
|------|---------|------------|
| W001 | Bare `dict`/`list` as final expression | Assign to variable first |
| W002 | Declared `@external` never called | Remove if unused |
| W003 | Declared `Input()` never referenced | Remove if unused |
| W004 | Script exceeds 200 lines | Break into smaller scripts or move logic to externals |

---

## 14. Scope of Work for .pym Scripts

### What .pym Scripts Are For

`.pym` scripts are designed for **short, focused business logic** that
orchestrates calls to host-provided functions. Think of them as
**configurable workflows** or **policy scripts** that:

- Coordinate multiple external function calls
- Apply conditional logic based on inputs
- Transform and aggregate data
- Return structured results

### Ideal Script Size

- **10–100 lines** is the sweet spot.
- **Under 200 lines** is recommended (W004 warns above this).
- If you're writing more than 200 lines, you're probably putting too much logic
  in the sandbox. Move complex computation to external functions.

### What Should Be in the Script vs. External Functions

| In the .pym Script | In External Functions (Host) |
|---------------------|------------------------------|
| Decision logic (if/else) | Database queries |
| Data aggregation (loops, sums) | API calls |
| Filtering and transformation | File I/O |
| Orchestration flow | Network requests |
| Threshold checks | Heavy computation |
| Result formatting | Authentication |
| Simple calculations | Logging and metrics |

### Good Use Cases

- **Policy evaluation:** "Given these inputs, should we approve this request?"
- **Data transformation:** "Take this data, apply these rules, return a summary."
- **Workflow orchestration:** "Fetch from A, then B, combine, decide, return."
- **Report generation logic:** "Query expenses, compare to budget, flag anomalies."
- **Configurable business rules:** "Apply discount logic that end-users can customize."

### Anti-Patterns

- **Heavy computation inside the sandbox** — move it to an external function.
- **Trying to import libraries** — use externals to wrap library calls.
- **Defining classes** — use dicts or have externals return structured data.
- **Complex state management** — keep scripts stateless; inputs in, result out.
- **Scripts longer than 200 lines** — decompose into multiple scripts or move
  logic to externals.

---

## 15. Complete Integration Example

This example shows a library that uses Grail to let users define custom
analysis rules.

**`analysis.pym`** — user-provided script:

```python
from grail import external, Input
from typing import Any

# Inputs from the host
budget_limit: float = Input("budget_limit")
department: str = Input("department", default="Engineering")

# Host-provided data access functions
@external
async def get_team_members(department: str) -> dict[str, Any]:
    """Get list of team members for a department."""
    ...

@external
async def get_expenses(user_id: int) -> dict[str, Any]:
    """Get expense line items for a user."""
    ...

@external
async def get_custom_budget(user_id: int) -> dict[str, Any] | None:
    """Get custom budget for a user if they have one."""
    ...

# Analysis logic
team_data = await get_team_members(department=department)
members = team_data.get("members", [])

over_budget = []

for member in members:
    uid = member["id"]
    expenses = await get_expenses(user_id=uid)
    items = expenses.get("items", [])

    total = sum(item["amount"] for item in items)

    if total > budget_limit:
        custom = await get_custom_budget(user_id=uid)
        if custom is None or total > custom.get("limit", budget_limit):
            over_budget.append({
                "user_id": uid,
                "name": member["name"],
                "total": total,
                "over_by": total - budget_limit,
            })

result = {
    "analyzed": len(members),
    "over_budget_count": len(over_budget),
    "details": over_budget,
}
result
```

**`host.py`** — your application:

```python
import asyncio
from grail import load, Limits, GrailError, LimitError, ExecutionError, ScriptEvent


async def get_team_members(department: str) -> dict:
    # Real implementation: query your database
    return {
        "members": [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 3, "name": "Charlie"},
        ]
    }


async def get_expenses(user_id: int) -> dict:
    # Real implementation: query your expense system
    expenses = {
        1: [{"amount": 3000}, {"amount": 2500}],
        2: [{"amount": 1000}],
        3: [{"amount": 4000}, {"amount": 2000}],
    }
    return {"items": expenses.get(user_id, [])}


async def get_custom_budget(user_id: int) -> dict | None:
    if user_id == 1:
        return {"limit": 6000.0}
    return None


def on_event(event: ScriptEvent):
    if event.type == "run_start":
        print(f"Starting {event.script_name}...")
    elif event.type == "run_complete":
        print(f"Completed in {event.duration_ms:.1f}ms")
    elif event.type == "run_error":
        print(f"Failed: {event.error}")


async def main():
    # Load with sensible defaults
    script = load(
        "analysis.pym",
        limits=Limits(max_memory="16mb", max_duration="5s"),
    )

    # Optional: run static checks
    check_result = script.check()
    if not check_result.valid:
        for error in check_result.errors:
            print(f"  [{error.code}] Line {error.lineno}: {error.message}")
        return

    for warning in check_result.warnings:
        print(f"  Warning [{warning.code}]: {warning.message}")

    # Execute
    try:
        result = await script.run(
            inputs={"budget_limit": 5000.0, "department": "Engineering"},
            externals={
                "get_team_members": get_team_members,
                "get_expenses": get_expenses,
                "get_custom_budget": get_custom_budget,
            },
            on_event=on_event,
        )

        print(f"Analyzed {result['analyzed']} team members")
        print(f"Found {result['over_budget_count']} over budget")
        for detail in result["details"]:
            print(f"  {detail['name']}: ${detail['total']:.2f} "
                  f"(over by ${detail['over_by']:.2f})")

    except LimitError as e:
        print(f"Script exceeded {e.limit_type} limit: {e}")
    except ExecutionError as e:
        print(f"Script error at line {e.lineno}: {e.message}")
    except GrailError as e:
        print(f"Grail error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
```

**Inspecting the script before running:**

```python
script = load("analysis.pym")

# See what the script expects
print(script.name)            # "analysis"
print(script.externals)       # dict of ExternalSpec objects
print(script.inputs)          # dict of InputSpec objects
print(script.monty_code)      # the generated Monty code
print(script.stubs)           # the generated .pyi stubs

# Check individual specs
for name, ext in script.externals.items():
    print(f"External: {name} (async={ext.is_async})")
    for param in ext.parameters:
        print(f"  param: {param.name}: {param.type_annotation}")
    print(f"  returns: {ext.return_type}")

for name, inp in script.inputs.items():
    print(f"Input: {name}: {inp.type_annotation} "
          f"(required={inp.required}, default={inp.default})")
```
