# Grail Specification

## Table of Contents

1. [Introduction](#1-introduction)
2. [Public API](#2-public-api)
3. [.pym File Format](#3-pym-file-format)
4. [CLI Specification](#4-cli-specification)
5. [Artifact Specification](#5-artifact-specification)
6. [Error Specification](#6-error-specification)
7. [Type Checking Specification](#7-type-checking-specification)
8. [Resource Limits Specification](#8-resource-limits-specification)
9. [Filesystem Specification](#9-filesystem-specification)
10. [Snapshot/Resume Specification](#10-snapshotresume-specification)

---

## 1. Introduction

Grail v3 is a Python library that provides a transparent, first-class programming experience for Monty (a secure Python-like interpreter written in Rust). Grail's purpose is to eliminate friction when writing code for Monty while maintaining visibility into Monty's limitations.

### Goals

- **Transparency**: Make Monty's limitations visible and manageable
- **Minimalism**: ~15 public symbols, everything else is implementation detail
- **Developer Experience**: Full IDE support for Monty code via `.pym` files
- **Safety**: Pre-flight validation catches Monty incompatibilities before runtime
- **Inspectability**: All generated artifacts visible in `.grail/` directory

### Non-Goals

- Generic observability (logging, metrics, retries)
- Complex abstraction layers over Monty
- Universal sandbox solutions (use Monty directly for those)
- Enterprise policy composition systems

---

## 2. Public API

### 2.1 Core Functions

#### `grail.load(path, **options) -> GrailScript`

Load and parse a `.pym` file.

**Parameters**:
- `path` (`str | Path`): Path to the `.pym` file (required)
- `limits` (`Limits | None`): Resource limits (default: `Limits.default()`)
- `files` (`dict[str, str | bytes] | None`): Virtual filesystem files (default: `None`)
- `environ` (`dict[str, str] | None`): Virtual environment variables (default: `None`)
- `grail_dir` (`str | Path | None`): Directory for generated artifacts (default: `".grail"`, `None` disables)
- `dataclass_registry` (`list[type] | None`): Types available for `isinstance()` checks (default: `None`)

**Returns**: `GrailScript` instance

**Raises**:
- `FileNotFoundError`: If `.pym` file doesn't exist
- `grail.ParseError`: If file has syntax errors
- `grail.CheckError`: If `@external` or `Input()` declarations are malformed

**Example**:
```python
import grail
from grail import Limits

script = grail.load("analysis.pym", limits=Limits.strict())
```

#### `grail.run(code, inputs) -> Any`

Execute inline Monty code (escape hatch for simple cases).

**Parameters**:
- `code` (`str`): Monty code to execute (required)
- `inputs` (`dict[str, Any]`): Input values (default: `{}`)
- `limits` (`Limits | None`): Resource limits
- `environ` (`dict[str, str] | None`): Virtual environment variables
- `print_callback` (`Callable[[str, str], None] | None`): Callback for print output

**Returns**: Result of final expression in code

**Example**:
```python
import grail

result = await grail.run("x + y", inputs={"x": 1, "y": 2})
# result == 3
```

**Note**: This is intentionally minimal — no externals, no type checking, no artifact generation. For complex scripts, use `.pym` files.

#### `grail.run_sync(code, inputs) -> Any`

Synchronous version of `grail.run()`.

### 2.2 GrailScript Class

#### Properties

| Property | Type | Description |
|---|---|---|
| `path` | `Path` | Original `.pym` file path |
| `name` | `str` | Script name (stem of filename) |
| `externals` | `dict[str, ExternalSpec]` | Extracted external function specs |
| `inputs` | `dict[str, InputSpec]` | Extracted input specs |
| `monty_code` | `str` | The processed code string for Monty |
| `stubs` | `str` | Generated type stub string |
| `limits` | `Limits` | Active resource limits |

#### Methods

##### `await script.run(inputs, externals, **kwargs) -> Any`

Execute the script in Monty and return the result.

**Parameters**:
- `inputs` (`dict[str, Any] | None`): Input values (default: `{}`)
- `externals` (`dict[str, Callable] | None`): External function implementations (default: `{}`)
- `output_model` (`type[BaseModel] | None`): Optional Pydantic model to validate return value (default: `None`)
- `files` (`dict[str, str | bytes] | None`): Override files from `load()` (default: `None`)
- `environ` (`dict[str, str] | None`): Override environ from `load()` (default: `None`)
- `limits` (`Limits | None`): Override limits from `load()` (default: `None`)
- `print_callback` (`Callable[[str, str], None] | None`): Callback for print() output (default: `None`)
- `on_event` (`Callable[[ScriptEvent], None] | None`): Callback for lifecycle events (default: `None`)
- `strict_validation` (`bool`): If `False`, extra inputs/externals produce warnings instead of errors (default: `True`)

**Behavior**:
- Validates all required inputs are provided
- Validates all declared externals have implementations
- Warns if extra inputs/externals are provided (in non-strict mode)
- Calls Monty with processed code and stubs
- Writes stdout/stderr to `.grail/<name>/run.log`
- Returns script's final expression value
- If `output_model` provided, validates result and returns model instance

**Raises**:
- `grail.InputError`: Missing required input or wrong type
- `grail.ExternalError`: Missing external function implementation
- `grail.ExecutionError`: Monty runtime error
- `grail.LimitError`: Resource limit exceeded (NOT a subclass of ExecutionError)
- `grail.OutputError`: Output validation failed

**Example**:
```python
result = await script.run(
    inputs={"budget_limit": 5000.0, "department": "Engineering"},
    externals={
        "get_team_members": get_team_members,
        "get_expenses": get_expenses,
        "get_custom_budget": get_custom_budget,
    },
)
```

##### `script.run_sync(inputs, externals, **kwargs) -> Any`

Synchronous wrapper around `run()`. Uses `asyncio.run()` internally.

**Parameters**: Same as `run()`

**Returns**: Same as `run()`

**Example**:
```python
result = script.run_sync(
    inputs={"budget_limit": 5000.0},
    externals={"get_team_members": get_team_members},
)
```

##### `script.check() -> CheckResult`

Run validation checks programmatically (same as `grail check` CLI).

**Returns**: `CheckResult` with validation results

**Example**:
```python
result = script.check()
if not result.valid:
    for error in result.errors:
        print(f"{error.lineno}:{error.col_offset}: {error.code} {error.message}")
```

### 2.3 Limits Class

```python
from grail import Limits

# Presets
Limits.strict()      # 8 MB memory, 500ms duration, 120 recursion depth
Limits.default()     # 16 MB memory, 2s duration, 200 recursion depth
Limits.permissive()  # 64 MB memory, 5s duration, 400 recursion depth

# Custom
limits = Limits(
    max_memory="32mb",
    max_duration="1.5s",
    max_recursion=300,
    max_allocations=100000,
    gc_interval=5000,
)
```

**Fields**:
| Field | Type | Description |
|-------|------|-------------|
| `max_memory` | `int \| str \| None` | Max heap memory in bytes (or `"16mb"`) |
| `max_duration` | `float \| str \| None` | Max execution time in seconds (or `"2s"`) |
| `max_recursion` | `int \| None` | Max call stack depth |
| `max_allocations` | `int \| None` | Max number of heap allocations |
| `gc_interval` | `int \| None` | GC frequency (every N allocations) |

`Limits` is a **frozen** Pydantic model — immutable after creation.

### 2.4 Declarations (for `.pym` files)

#### `grail.external`

Decorator to declare external functions in `.pym` files.

**Usage**:
```python
from grail import external

@external
async def fetch_data(url: str) -> dict[str, Any]:
    """Fetch data from URL."""
    ...
```

**Requirements**:
- Complete type annotations on parameters and return type
- Function body must be `...` (Ellipsis)
- Can be `async def` or `def`

#### `grail.Input(name, default=...)`

Declare input variables in `.pym` files.

**Usage**:
```python
from grail import Input

budget_limit: float = Input("budget_limit")
department: str = Input("department", default="Engineering")
```

**Parameters**:
- `name` (`str`): Input variable name (must match variable name)
- `default` (`Any | None`): Optional default value

**Requirements**:
- Must have type annotation

### 2.5 Snapshot Class (Deferred)

The snapshot/resume feature is deferred. When Monty adds native support, Grail will expose it.

### 2.6 Error Types

```python
grail.GrailError (base)
├── grail.ParseError
├── grail.CheckError
├── grail.InputError
├── grail.ExternalError
├── grail.ExecutionError
│   └── grail.LimitError  # NOTE: LimitError is NOT a subclass of ExecutionError
└── grail.OutputError
```

**Important**: `LimitError` inherits directly from `GrailError`, NOT from `ExecutionError`. This is intentional — resource limits are fundamentally different from code bugs.

### 2.7 Check Result Types

```python
@dataclass
class CheckMessage:
    code: str                      # "E001", "W001", etc.
    lineno: int
    col_offset: int
    end_lineno: int | None
    end_col_offset: int | None
    severity: Literal['error', 'warning']
    message: str
    suggestion: str | None

@dataclass
class CheckResult:
    file: str
    valid: bool
    errors: list[CheckMessage]
    warnings: list[CheckMessage]
    info: dict[str, Any]
    messages: list[CheckMessage]  # Combined errors + warnings
```

### 2.8 ScriptEvent

```python
@dataclass
class ScriptEvent:
    type: str  # "run_start", "run_complete", "run_error", "print", "check_start", "check_complete"
    script_name: str
    timestamp: float
    text: str | None = None
    duration_ms: float | None = None
    error: str | None = None
    input_count: int | None = None
    external_count: int | None = None
    result_summary: str | None = None
```

---

## 3. .pym File Format

### 3.1 Overview

`.pym` (Python for Monty) files are valid Python files intended to run inside Monty. IDEs treat them as Python with full syntax highlighting, autocomplete, and type checking.

### 3.2 Syntax

```python
# analysis.pym

from grail import external, Input
from typing import Any

# --- Declarations Section ---
# These are metadata markers that grail tooling reads.

budget_limit: float = Input("budget_limit")
department: str = Input("department", default="Engineering")

@external
async def get_team_members(department: str) -> dict[str, Any]:
    """Get list of team members for a department."""
    ...

@external
async def get_expenses(user_id: int, quarter: str, category: str) -> dict[str, Any]:
    """Get expense line items for a user."""
    ...

# --- Executable Section ---
# Everything below is the actual Monty script.

team_data = await get_team_members(department=department)
members = team_data.get("members", [])

# ... rest of script ...

{
    "analyzed": len(members),
    "over_budget_count": len(over_budget),
    "details": over_budget,
}
```

### 3.3 Rules

1. **MUST** be syntactically valid Python 3.10+
2. `@external` functions **MUST** have complete type annotations (parameters + return)
3. `@external` function bodies **MUST** be `...` (Ellipsis)
4. `Input()` declarations **MUST** have a type annotation
5. All imports except `from grail import ...`, `from typing import ...`, and `from __future__ import ...` are forbidden
6. File's return value is its final expression (like a Jupyter cell)

### 3.4 Supported Python Features

- Functions and closures
- Async/await
- Comprehensions (list, dict, set, generator expressions)
- Basic data structures (int, float, str, bool, list, dict, tuple, set, None)
- Control flow (if/elif/else, for, while, try/except/finally)
- F-strings
- Type annotations
- `isinstance()` (for registered dataclasses)
- `os.getenv()` (for virtual environment variables)

### 3.5 Unsupported Python Features

- Classes
- Generators and `yield`
- `with` statements
- `match` statements
- Lambda expressions
- Imports beyond `grail`, `typing`, and `__future__`
- Most of the standard library

---

## 4. CLI Specification

### 4.1 Commands

#### `grail init`

Initialize a project for grail usage.

**Usage**:
```bash
grail init
```

**Creates**:
- `.grail/` directory
- Adds `.grail/` to `.gitignore` (if exists)
- Creates sample `.pym` file
- Prints getting-started message

#### `grail check [files...]`

Validate `.pym` files against Monty's constraints.

**Usage**:
```bash
# Check all .pym files in current directory (recursive)
grail check

# Check specific files
grail check analysis.pym sentiment.pym

# JSON output (for CI integration)
grail check --format json

# Strict mode — warnings become errors
grail check --strict
```

**Validates**:

| Check | Code | Severity | Example |
|---|---|---|---|
| Class definitions | E001 | Error | `class Foo: ...` |
| Generator/yield | E002 | Error | `def gen(): yield 1` |
| `with` statements | E003 | Error | `with open(f): ...` |
| `match` statements | E004 | Error | `match x: ...` |
| Forbidden imports | E005 | Error | `import json` |
| Missing type annotations on `@external` | E006 | Error | Parameters and return type required |
| `@external` with non-ellipsis body | E007 | Error | Body must be `...` |
| `Input()` without type annotation | E008 | Error | Type required |
| `global` statement | E009 | Error | Use params/returns |
| `nonlocal` statement | E010 | Error | Use params/returns |
| `del` statement | E011 | Error | Don't delete variables |
| `lambda` expression | E012 | Error | Use `def` instead |
| Monty type checker errors | E100 | Error | From `ty` |
| Bare dict/list as return value | W001 | Warning | Consider naming for clarity |
| Unused `@external` function | W002 | Warning | Declared but never called |
| Unused `Input()` variable | W003 | Warning | Declared but never referenced |
| Very long script (>200 lines) | W004 | Warning | May indicate too much logic |

**Output**:
```
analysis.pym: OK (3 externals, 2 inputs, 0 errors, 1 warning)
sentiment.pym: FAIL
  sentiment.pym:12:1: E001 Class definitions are not supported in Monty
  sentiment.pym:25:5: E003 'with' statements are not supported in Monty

Checked 2 files: 1 passed, 1 failed
```

#### `grail run <file.pym> [--host <host.py>]`

Execute a `.pym` file.

**Usage**:
```bash
# Run with a host file
grail run analysis.pym --host host.py

# Run with inline inputs
grail run analysis.pym --host host.py --input budget_limit=5000
```

#### `grail watch [dir]`

File watcher that re-runs `grail check` on `.pym` file changes.

**Usage**:
```bash
# Watch current directory
grail watch

# Watch specific directory
grail watch src/scripts/
```

#### `grail clean`

Remove the `.grail/` directory.

**Usage**:
```bash
grail clean
```

---

## 5. Artifact Specification

### 5.1 Directory Structure

```
.grail/
├── <script_name>/
│   ├── stubs.pyi        # Generated type stubs
│   ├── check.json       # Validation results
│   ├── externals.json   # External function specs
│   ├── inputs.json      # Input declarations
│   ├── monty_code.py   # Stripped Monty code
│   └── run.log         # Execution output
```

### 5.2 stubs.pyi

Type stubs sent to Monty's `ty` type checker.

### 5.3 check.json

Results of `grail check`.

### 5.4 externals.json

Machine-readable extraction of external function signatures.

### 5.5 inputs.json

Machine-readable extraction of input declarations.

### 5.6 monty_code.py

Actual Python code sent to Monty interpreter.

### 5.7 run.log

Combined stdout/stderr from execution.

---

## 6. Error Specification

### 6.1 Error Hierarchy

```
grail.GrailError (base)
├── grail.ParseError          # .pym file has syntax errors
├── grail.CheckError          # @external or Input() declarations are malformed
├── grail.InputError          # missing/invalid input at runtime
├── grail.ExternalError       # missing external function implementation
├── grail.ExecutionError      # Monty runtime error
└── grail.LimitError          # resource limit exceeded (NOT a subclass of ExecutionError)
└── grail.OutputError         # output validation failed
```

### 6.2 Error Format

All errors reference the original `.pym` file, not generated `monty_code.py`. Grail maintains a source map between the two.

**Example**:
```
grail.ExecutionError: analysis.pym:22 — NameError: name 'undefined_var' is not defined

  20 |     total = sum(item["amount"] for item in items)
  21 |
> 22 |     if total > undefined_var:
  23 |         custom = await get_custom_budget(user_id=uid)

Context: This variable is not defined in the script and is not a declared Input().
```

### 6.3 Error Details

| Error | Attributes |
|-------|------------|
| `ParseError` | `message`, `lineno`, `col_offset` |
| `CheckError` | `message`, `lineno` |
| `InputError` | `message`, `input_name` |
| `ExternalError` | `message`, `function_name` |
| `ExecutionError` | `message`, `lineno`, `col_offset`, `source_context`, `suggestion` |
| `LimitError` | `message`, `limit_type` (memory, duration, recursion, allocations) |
| `OutputError` | `message`, `validation_errors` |

---

## 7. Type Checking Specification

### 7.1 How It Works

1. Developer writes `@external` functions with full type annotations in `.pym` file
2. `grail.load()` parses these with `ast` and generates `.pyi` stubs
3. Stubs are passed to Monty's built-in `ty` type checker
4. `grail check` reports type errors before execution

### 7.2 Supported Types

Stubs support all types that Monty's `ty` checker understands:

- Primitives: `int`, `float`, `str`, `bool`, `None`
- Collections: `list[T]`, `dict[K, V]`, `tuple[T, ...]`, `set[T]`
- Unions: `T | None`, `int | str`
- `Any`
- Nested combinations of the above

---

## 8. Resource Limits Specification

### 8.1 Design

`Limits` is a Pydantic model with preset constructors. No policies, no inheritance, no composition.

```python
from grail import Limits

script = grail.load("analysis.pym", limits=Limits(
    max_memory="16mb",
    max_duration="5s",
    max_recursion=200,
))
```

### 8.2 Presets

```python
Limits.strict()      # 8 MB memory, 500ms duration, 120 recursion depth
Limits.default()     # 16 MB memory, 2s duration, 200 recursion depth
Limits.permissive()  # 64 MB memory, 5s duration, 400 recursion depth
```

### 8.3 String Format Parsing

**Memory**: `"16mb"` → `16 * 1024 * 1024`, `"1gb"` → `1 * 1024 * 1024 * 1024` (case insensitive)

**Duration**: `"500ms"` → `0.5`, `"2s"` → `2.0`, `"1.5s"` → `1.5` (case insensitive)

### 8.4 Override at Runtime

```python
# Load with defaults, override per-run
script = grail.load("analysis.pym")
result = await script.run(
    inputs={...},
    externals={...},
    limits=Limits(max_duration="10s"),  # override just this one
)
```

Merging replaces only non-`None` fields from the override.

---

## 9. Filesystem Specification

### 9.1 Design

Dict in, Monty `OSAccess` out.

```python
script = grail.load("analysis.pym", files={
    "/data/customers.csv": Path("customers.csv").read_text(),
    "/data/tweets.json": Path("tweets.json").read_text(),
})
```

### 9.2 Virtual Environment Variables

```python
script = grail.load("analysis.pym", environ={
    "API_KEY": "abc123",
})
```

Inside the script: `os.getenv("API_KEY")` returns `"abc123"`.

### 9.3 Dynamic Files

If you need files determined at runtime, pass them to `run()`:

```python
result = await script.run(
    inputs={...},
    externals={...},
    files={"/data/report.csv": generate_csv()},
)
```

Run-time overrides **completely replace** load-time values.

---

## 10. Snapshot/Resume Specification

**Status: Deferred**

Snapshot/resume is not included in v3. When Monty adds native support, Grail will expose it.

---

## Appendix A: Migration from Grail v1/v2

This is a clean break. No automated migration.

### For Previous Grail Users

1. **Convert code strings to `.pym` files** — move sandboxed code out of Python strings
2. **Replace `MontyContext` with `grail.load()`** — many constructor parameters become optional kwargs
3. **Replace `ToolRegistry` with a plain dict** — `externals={"name": func}`
4. **Replace `GrailFilesystem` with a plain dict** — `files={"/path": content}`
5. **Replace resource policies with `Limits` model** — use `Limits.strict()`, `.default()`, `.permissive()`
6. **Remove observability code** — add your own `logging`/metrics at application level
7. **Remove `@secure` decorators** — use `.pym` files instead
8. **Run `grail check`** — catch Monty compatibility issues immediately

---

## Appendix B: Public API Summary

**Total: ~15 public symbols**

```python
# Core
grail.load(path, **options) -> GrailScript
grail.run(code, inputs) -> Any
grail.run_sync(code, inputs) -> Any

# Declarations (for .pym files)
grail.external
grail.Input(name, default=...)

# Limits
grail.Limits
grail.Limits.strict() -> Limits
grail.Limits.default() -> Limits
grail.Limits.permissive() -> Limits

# Events
grail.ScriptEvent

# Errors
grail.GrailError
grail.ParseError
grail.CheckError
grail.InputError
grail.ExternalError
grail.ExecutionError
grail.LimitError
grail.OutputError

# Check results
grail.CheckResult
grail.CheckMessage
```
