# Grail

Grail is a Python library that enables sandboxed script execution via [Monty](https://pypi.org/project/pydantic-monty/), a secure Python interpreter written in Rust. You write `.pym` files (a restricted Python dialect), and Grail parses, validates, code-generates, and executes them inside an isolated runtime where scripts cannot access the filesystem, network, or arbitrary modules.

## Installation

Requires **Python >= 3.13**.

```bash
pip install grail
```

For file-watching support (optional):

```bash
pip install grail[watch]
```

## Quick Start

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

## Core Concepts

| Concept | Description |
|---------|-------------|
| `.pym` file | A restricted Python file with `@external` and `Input()` declarations. |
| `@external` | A decorator that declares a function the **host** will provide at runtime. |
| `Input()` | A function that declares a named value the host will inject at runtime. |
| `GrailScript` | The main class created by `grail.load()`. Encapsulates parsed metadata, generated code, and provides `check()`, `run()`, and `run_sync()`. |
| Monty | The sandboxed Python interpreter (Rust-based) that actually executes the code. |
| `Limits` | A Pydantic model controlling memory, duration, recursion, and allocation limits. |
| `.grail/` | An optional artifacts directory containing generated stubs, Monty code, check results, and run logs. |

## Documentation

- **[How to Use Grail](HOW_TO_USE_GRAIL.md)** — Comprehensive developer guide covering all features
- [Architecture](ARCHITECTURE.md) — Internal design and module structure
- [Specification](SPEC.md) — Technical API reference

## License

MIT
