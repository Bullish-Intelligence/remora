# Grail Architecture

## Overview

Grail v3 is a minimalist Python library that provides a transparent, first-class programming experience for Monty (a secure Python interpreter written in Rust). Grail sits between developers and Monty, eliminating friction while maintaining visibility into Monty's limitations.

### Core Design Principles

1. **Transparency over Abstraction** — Make Monty's limitations visible and manageable, not hidden
2. **Minimal Surface Area** — ~15 public symbols, everything else is implementation detail
3. **Files as First-Class Citizens** — `.pym` files with full IDE support
4. **Pre-Flight Validation** — Catch Monty compatibility issues before runtime
5. **Inspectable Internals** — All generated artifacts visible in `.grail/` directory

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Grail Library                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐ │
│  │   CLI Layer  │      │ Parser Layer │      │  Core API    │ │
│  │              │      │              │      │              │ │
│  │  grail check │◄────►│  .pym Parser │◄────►│ grail.load() │ │
│  │  grail run   │      │  AST Walker  │      │ GrailScript  │ │
│  │  grail init  │      │              │      │              │ │
│  └──────────────┘      └──────────────┘      └──────────────┘ │
│           │                    │                    │           │
│           ▼                    ▼                    ▼           │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐ │
│  │  Artifacts   │      │   Checker    │      │   Stubs      │ │
│  │   Manager    │      │              │      │   Generator  │ │
│  │              │      │ Monty Rules  │      │              │ │
│  │  .grail/     │      │ Type Errors  │      │ .pyi Format  │ │
│  └──────────────┘      └──────────────┘      └──────────────┘ │
│                                                                   │
└─────────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
               ┌───────────────────────────────┐
               │    Monty (pydantic-monty)   │
               │   Rust Python Interpreter    │
               └───────────────────────────────┘
```

## Module Structure

```
src/grail/
├── __init__.py          # Public API surface (~15 symbols)
├── script.py            # GrailScript: load, parse, run, check
├── parser.py           # Parse .pym files, extract @external and Input()
├── checker.py          # Monty compatibility validation
├── stubs.py            # Generate .pyi stubs from declarations
├── codegen.py          # Transform .pym → monty_code.py
├── artifacts.py       # Manage .grail/ directory artifacts
├── limits.py           # Resource limits parsing & presets (Pydantic model)
├── errors.py           # Error hierarchy with source mapping
├── cli.py              # CLI entry point (grail check, run, init, watch)
├── _types.py          # Type stubs for grail module (PEP 561)
├── _external.py       # @external decorator implementation
├── _input.py          # Input() function implementation
└── py.typed           # PEP 561 marker
```

## Core Components

### 1. Parser (`parser.py`)

**Responsibility**: Parse `.pym` files and extract metadata

**Key Operations**:
- Use Python's `ast` module to parse `.pym` files
- Walk AST to find `@external` decorated functions
- Extract function signatures: name, parameters, return type, docstring
- Find `Input()` calls and extract input declarations
- Validate AST structure (no classes, generators, `with`, `match` statements)
- Build source map between `.pym` lines and generated code

**Data Structures**:
```python
@dataclass
class ExternalSpec:
    name: str
    is_async: bool
    parameters: list[ParamSpec]
    return_type: str
    docstring: str | None
    lineno: int
    col_offset: int

@dataclass
class InputSpec:
    name: str
    type_annotation: str
    default: Any | None
    required: bool
    lineno: int
    col_offset: int

@dataclass
class ParseResult:
    externals: dict[str, ExternalSpec]
    inputs: dict[str, InputSpec]
    ast: ast.Module
    source_lines: list[str]
```

### 2. Checker (`checker.py`)

**Responsibility**: Validate Monty compatibility and detect errors

**Key Operations**:
- Detect forbidden Python features (classes, generators, `with`, `match`, lambda, etc.)
- Validate import statements (only `grail`, `typing`, and `__future__` allowed)
- Check `@external` function bodies are `...` (Ellipsis)
- Check `Input()` has type annotations
- Run Monty's `ty` type checker on generated stubs
- Produce structured error/warning/info messages

**Check Categories**:
- **Errors (E0xx)**: Block execution (e.g., class definition, forbidden import)
- **Errors (E1xx)**: Type checker errors from `ty`
- **Warnings (W0xx)**: Advisory (e.g., unused declarations, bare dict returns)
- **Info**: Statistics (e.g., lines of code, Monty features used)

**Data Structures**:
```python
@dataclass
class CheckMessage:
    code: str  # E001, W001, etc.
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
```

### 3. Stubs Generator (`stubs.py`)

**Responsibility**: Generate Monty-compatible `.pyi` stub files

**Key Operations**:
- Convert `ExternalSpec` → stub function signature
- Convert `InputSpec` → stub variable declaration
- Generate import statements (`from typing import Any`, etc.)
- Format as valid Python stub file
- Write to `.grail/<name>/stubs.pyi`

**Example Output**:
```python
# .grail/analysis/stubs.pyi
# Auto-generated by grail — do not edit
from typing import Any

budget_limit: float
department: str

async def get_team_members(department: str) -> dict[str, Any]:
    """Get list of team members for a department."""
    ...
```

### 4. Code Generator (`codegen.py`)

**Responsibility**: Transform `.pym` file to Monty-compatible code

**Key Operations**:
- Strip `from grail import ...` statements
- Remove `@external` decorated function definitions
- Remove `Input()` calls (they become runtime bindings)
- Preserve executable code section
- Generate line number mapping table
- Handle edge cases (multiple assignments, nested structures)

**Data Structures**:
```python
@dataclass
class SourceMap:
    """Maps monty_code.py line numbers back to .pym line numbers"""
    monty_lines: dict[int, int]  # monty_line → pym_line
    pym_lines: dict[int, int]      # pym_line → monty_line

@dataclass
class CodegenResult:
    code: str
    source_map: SourceMap
```

### 5. Artifacts Manager (`artifacts.py`)

**Responsibility**: Manage `.grail/` directory structure

**Key Operations**:
- Create `.grail/<name>/` directory hierarchy
- Write individual artifact files (stubs.pyi, check.json, etc.)
- Generate JSON metadata (externals.json, inputs.json)
- Write monty_code.py and run.log
- Clean directory on `grail clean`
- Optional: disable artifact generation with `grail_dir=None`

**Directory Structure**:
```
.grail/
├── <script_name>/
│   ├── stubs.pyi        # Generated type stubs
│   ├── check.json       # Validation results
│   ├── externals.json   # External function specs
│   ├── inputs.json      # Input declarations
│   ├── monty_code.py    # Stripped Monty code
│   └── run.log         # Execution output
```

### 6. Core Script (`script.py`)

**Responsibility**: Main API: load, parse, check, run scripts

**Key Class**: `GrailScript`

**Lifecycle**:
1. **Load Phase** (`grail.load()`):
   - Read `.pym` file
   - Parse with `parser.py`
   - Validate with `checker.py`
   - Generate stubs with `stubs.py`
   - Generate code with `codegen.py`
   - Write artifacts
   - Return `GrailScript` instance

2. **Check Phase** (`script.check()`):
   - Run `checker.py` validation
   - Call Monty's type checker
   - Return `CheckResult`

3. **Run Phase** (`script.run()`):
   - Validate inputs against declared `Input()` specs
   - Validate externals against `@external` declarations
   - Transform resource limits to Monty format
   - Transform files dict to `OSAccess` with `MemoryFile`
   - Transform environ dict to virtual env vars
   - Call Monty
   - Map errors back to `.pym` line numbers
   - Write run.log
   - Return result

**Data Structures**:
```python
class GrailScript:
    path: Path
    name: str
    externals: dict[str, ExternalSpec]
    inputs: dict[str, InputSpec]
    monty_code: str
    stubs: str
    source_map: SourceMap
    limits: Limits | None
    grail_dir: Path | None

    def run(self, inputs, externals, **kwargs) -> Any
    def run_sync(self, inputs, externals, **kwargs) -> Any
    def check(self) -> CheckResult
```

### 7. Limits (`limits.py`)

**Responsibility**: Parse and validate resource limits

**Key Operations**:
- Parse string formats (`"16mb"` → `16 * 1024 * 1024`, `"2s"` → `2.0`)
- Validate limit values
- Provide named presets via class methods (`strict()`, `default()`, `permissive()`)
- Merge limits (load-time with run-time overrides)

**Implementation**: Frozen Pydantic model

```python
class Limits(BaseModel):
    max_memory: int | str | None = None
    max_duration: float | str | None = None
    max_recursion: int | None = None
    max_allocations: int | None = None
    gc_interval: int | None = None

    def strict() -> Limits: ...
    def default() -> Limits: ...
    def permissive() -> Limits: ...
```

**Presets**:
| Preset | Memory | Duration | Recursion |
|--------|--------|----------|-----------|
| `strict()` | 8 MB | 500 ms | 120 |
| `default()` | 16 MB | 2 s | 200 |
| `permissive()` | 64 MB | 5 s | 400 |

### 8. Errors (`errors.py`)

**Responsibility**: Error hierarchy with source mapping

**Key Operations**:
- Define exception hierarchy
- Format errors with `.pym` context
- Map Monty tracebacks to `.pym` line numbers using source map
- Show surrounding code context

**Hierarchy**:
```
GrailError (base)
├── ParseError          # .pym file has syntax errors
├── CheckError          # @external or Input() malformed
├── InputError          # missing/invalid input at runtime
├── ExternalError       # missing external function implementation
├── ExecutionError      # Monty runtime error
├── LimitError          # resource limit exceeded (NOT a subclass of ExecutionError)
└── OutputError         # output validation failed
```

**Important**: `LimitError` inherits directly from `GrailError`, NOT from `ExecutionError`. This is intentional — resource limits are fundamentally different from code bugs.

**Error Format**:
```
grail.ExecutionError: analysis.pym:22 — NameError: name 'undefined_var' is not defined

  20 |     total = sum(item["amount"] for item in items)
  21 |
> 22 |     if total > undefined_var:
  23 |         custom = await get_custom_budget(user_id=uid)

Context: This variable is not defined in the script and is not a declared Input().
```

### 9. CLI (`cli.py`)

**Responsibility**: Command-line interface for grail tooling

**Commands**:
- `grail init`: Initialize project, create sample `.pym`
- `grail check [files...]`: Validate `.pym` files
- `grail run <file.pym> [--host <host.py>]`: Execute script
- `grail watch [dir]`: Watch and re-run `grail check`
- `grail clean`: Remove `.grail/` directory

**Implementation**:
- Use `argparse` for CLI parsing
- Delegate to core modules (`parser`, `checker`, `script`)
- Format output for terminal (color, symbols)
- Support JSON output for CI integration

## Data Flow

### Loading a `.pym` File

```
1. User calls grail.load("analysis.pym")
   ↓
2. script.py reads file content
   ↓
3. parser.py parses AST, extracts:
   - @external declarations → ExternalSpec[]
   - Input() calls → InputSpec[]
   - Source lines for source mapping
   ↓
4. checker.py validates AST (no classes, forbidden imports)
   ↓
5. stubs.py generates .pyi file from ExternalSpec[] and InputSpec[]
   ↓
6. codegen.py strips grail imports, generates monty_code.py
   ↓
7. artifacts.py writes to .grail/analysis/:
   - stubs.pyi
   - externals.json
   - inputs.json
   - monty_code.py
   ↓
8. Returns GrailScript instance
```

### Running a Script

```
1. User calls script.run(inputs={...}, externals={...})
   ↓
2. Validate inputs match Input[] declarations
   ↓
3. Validate externals match @external[] declarations
   ↓
4. Transform Limits to Monty format
   ↓
5. Transform files dict to OSAccess with MemoryFile[]
   ↓
6. Transform environ dict to virtual env vars
   ↓
7. Create Monty instance with monty_code and stubs
   ↓
8. Execute script
   ↓
9. Map any errors to .pym line numbers via source_map
   ↓
10. Write stdout/stderr to .grail/analysis/run.log
   ↓
11. Return result (optionally validated against output_model)
```

## Monty Integration

### Resource Limits Mapping

| Grail Limit | Monty Limit | Notes |
|---|---|---|
| `max_memory="16mb"` | `max_memory=16777216` | Parse string → bytes |
| `max_duration="2s"` | `max_duration_secs=2.0` | Parse string → seconds |
| `max_recursion=200` | `max_recursion_depth=200` | Direct pass-through |
| `max_allocations=None` | `max_allocations=None` | Optional |
| `gc_interval=5000` | `gc_interval=5000` | Optional |

### Filesystem Mapping

```python
# Grail input:
files = {
    "/data/customers.csv": "id,name\n1,Alice\n",
    "/data/tweets.json": b'{"user": "..."}',
}

# Transformed to Monty:
fs = OSAccess([
    MemoryFile("/data/customers.csv", content="id,name\n1,Alice\n"),
    MemoryFile("/data/tweets.json", content=b'{"user": "..."}'),
])
```

### Environment Variables Mapping

```python
# Grail input:
environ = {"API_KEY": "abc123", "ENV": "production"}

# Inside Monty:
# os.getenv("API_KEY") returns "abc123"
# os.getenv("ENV") returns "production"
```

### Type Checking Integration

```python
# Grail generates stubs:
stubs = """
from typing import Any

async def get_data(id: int) -> dict[str, Any]:
    ...
"""

# Pass to Monty:
m = pydantic_monty.Monty(
    monty_code,
    type_check=True,
    type_check_stubs=stubs,
)
```

## Dependencies

### Runtime Dependencies
- `pydantic-monty`: Monty Python bindings (required)
- `pydantic >= 2.12.5`: For Limits model and output validation
- `ast`: Built-in Python module (for parsing)
- `typing`: Built-in Python module

### Development Dependencies
- `pytest`: Testing framework
- `mypy`: Static type checking
- `ruff`: Linting and formatting
- `pytest-asyncio`: Async test support

### Optional Dependencies
- `watchfiles`: For `grail watch` file watching

## Extension Points

### Adding Monty Feature Checks

When Monty adds new features (e.g., classes, `match` statements), update `checker.py`:

```python
# In checker.py
def check_classes(node: ast.AST) -> CheckMessage | None:
    """Check if classes are allowed in Monty."""
    if MONTY_SUPPORTS_CLASSES:
        return None
    return CheckMessage(
        code="E001",
        severity="error",
        message="Class definitions are not supported in Monty",
        ...
    )
```

### Custom File Types

To support custom file backends (e.g., S3), users pass external functions instead:

```python
# In .pym:
@external
async def read_s3(path: str) -> str:
    ...

# In host code:
script.run(
    externals={
        "read_s3": lambda path: s3_client.get_object(path),
    },
)
```

### Custom Output Validation

Use the `output_model` parameter with Pydantic:

```python
from pydantic import BaseModel

class Report(BaseModel):
    analyzed: int
    over_budget_count: int

result = await script.run(
    inputs={...},
    externals={...},
    output_model=Report,
)
# result is validated Report instance
```

## Performance Considerations

### Startup Time
- `.pym` parsing: ~1-2ms (AST walking)
- Stub generation: <1ms (string formatting)
- Artifact writing: <5ms (file I/O, optional with `grail_dir=None`)
- Monty parsing: Dominant cost (~0.06ms)
- **Total**: <10ms overhead over bare Monty

### Runtime Overhead
- Input validation: <1ms
- External function lookup: O(1) dict access
- Source map lookup: O(1) dict access
- **Total**: Negligible (sub-millisecond)

### Memory Usage
- Source map: ~1KB per 100 lines of code
- Cached AST: Proportional to source size
- Artifacts: ~5-10KB per script (stubs, JSON metadata)
- **Total**: <1MB for typical projects

## Security Model

Grail inherits Monty's security model:

1. **Sandbox**: Monty code runs in Rust interpreter, cannot access host
2. **External Functions**: Only explicitly provided functions are callable
3. **Filesystem**: Only `MemoryFile` objects in `OSAccess` are accessible
4. **Resource Limits**: Enforced by Monty (memory, time, recursion)
5. **No Eval/Exec**: Monty doesn't support `eval()` or `exec()`

Grail adds:

1. **Pre-Flight Validation**: Catch Monty incompatibilities before runtime
2. **Type Safety**: Input/output type checking
3. **Inspectable Artifacts**: All generated code visible in `.grail/`

## Testing Strategy

### Unit Tests
- `test_parser.py`: AST extraction, validation
- `test_checker.py`: Monty rule detection
- `test_stubs.py`: Stub generation from specs
- `test_codegen.py`: Code transformation
- `test_limits.py`: Limit parsing and validation
- `test_errors.py`: Error formatting and mapping

### Integration Tests
- `test_script.py`: Full load → check → run workflow
- `test_artifacts.py`: Artifact generation and cleanup
- `test_cli.py`: CLI command execution

### E2E Tests
- `test_real_workflows.py`: Example scripts
- `test_monty_integration.py`: Direct Monty compatibility
- `test_type_checking.py`: Monty's type checker integration

### Property Tests
- Source map correctness (bidirectional mapping)
- Limit parsing (all valid formats)

## Future Considerations

### When Monty Adds Classes
- Introduce `GrailModel` base class
- Compile to Monty dataclasses or TypedDict
- Generate type stubs from class definitions

### When Monty Adds `match` Statements
- Remove E004 check
- Update documentation

### Advanced Features
- `.pym` file watching with hot reload
- Remote execution (serializable snapshots across network)
- Distributed execution (multiple Monty instances coordinating)
- IDE extensions (VS Code plugin with syntax highlighting)
